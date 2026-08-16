"""Account registration and authentication.

Services own the translation between result rows and domain models. Nothing
above this layer sees a driver dict, and nothing below it knows what HTTP is.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from neo4j.exceptions import ConstraintError

from app.core.exceptions import ResourceNotFoundError, VouchError
from app.core.logging import get_logger
from app.core.security import hash_account_password, verify_account_password
from app.db.client import GraphClient
from app.db.cypher.accounts import (
    CREATE_ACCOUNT_CYPHER,
    FIND_ACCOUNT_BY_EMAIL_CYPHER,
    FIND_ACCOUNT_BY_ID_CYPHER,
    PERSON_EXISTS_CYPHER,
)
from app.models.account import Account, AccountCreate, Credentials

log = get_logger("account_service")

#: Verified on every "no such account" authenticate() call so that branch
#: costs the same as a real password check -- see authenticate() for why.
_DUMMY_PASSWORD_HASH = hash_account_password("this is never a real account's password")


class EmailAlreadyRegisteredError(VouchError):
    """Sign-up used an address that already has an account."""

    status_code = 409
    user_message = "That email address already has an account. Try signing in."


def _row_to_account(row: Mapping[str, Any]) -> Account:
    """Build an Account from a result row, stripping ``password_hash`` if present.

    Explicit and identical at every call site rather than left implicit in
    some of them (a statement that happens not to project the field, plus
    pydantic's default ``extra="ignore"``) -- both are safe today, but two
    different, silent mechanisms doing the same job is exactly how "safe"
    stops being obviously true after the next edit to either one.
    """
    return Account.model_validate({k: v for k, v in row.items() if k != "password_hash"})


class AccountService:
    def __init__(self, graph: GraphClient) -> None:
        self._graph = graph

    async def register(self, data: AccountCreate) -> Account:
        """Create an account linked to an existing person.

        Sign-up claims an existing person in the seeded network rather than
        creating a new one: the graph is the dataset, and an account with no
        connections would have no routes and nothing to show.

        The pre-check below is a fast path for a friendly error message on the
        common, non-concurrent case -- it is inherently racy (check-then-
        write) and is *not* the safety mechanism. What actually makes two
        simultaneous sign-ups for the same address safe is the UNIQUE
        constraint on ``Account.email`` applied by the migration, together
        with the ``except ConstraintError`` below: the losing `MERGE` in a
        concurrent pair fails at the database with ``ConstraintError`` (a
        ``ClientError`` subclass ``GraphClient`` re-raises untranslated,
        confirmed against a live duplicate insert), and that handler is what
        turns the loser's failure into the same friendly 409 the pre-check
        gives the non-concurrent case, instead of an unhandled 500.
        """
        if not await self._graph.read(PERSON_EXISTS_CYPHER, {"person_id": data.person_id}):
            raise ResourceNotFoundError("We couldn't find that person in the network.")

        if await self._graph.read(FIND_ACCOUNT_BY_EMAIL_CYPHER, {"email": data.email}):
            raise EmailAlreadyRegisteredError()

        try:
            rows = await self._graph.write(
                CREATE_ACCOUNT_CYPHER,
                {
                    "account_id": str(uuid.uuid4()),
                    "email": data.email,
                    "password_hash": hash_account_password(data.password),
                    "person_id": data.person_id,
                },
            )
        except ConstraintError as exc:
            raise EmailAlreadyRegisteredError() from exc
        if not rows:
            raise ResourceNotFoundError("Could not create the account.")
        log.info("registered account for person %s", data.person_id)
        return _row_to_account(rows[0])

    async def authenticate(self, creds: Credentials) -> Account | None:
        """Verify credentials.

        Returns None for both "no such email" and "wrong password", and logs
        neither the address nor the attempt outcome in a way that distinguishes
        them -- telling an attacker which addresses are registered is a free
        account-enumeration oracle.

        The "no such email" branch also runs a throwaway password verification
        against a fixed dummy hash before returning, so both branches pay the
        same scrypt cost. This is not closing a measured timing exploit --
        the ~500ms round trip to the graph almost certainly swamps a
        scrypt-sized difference in practice, and nobody has measured otherwise
        here. It's done because a defence that relies on ambient network noise
        to stay safe isn't a defence, and the cost is one extra hash.
        """
        rows = await self._graph.read(FIND_ACCOUNT_BY_EMAIL_CYPHER, {"email": creds.email})
        if not rows:
            verify_account_password(creds.password, _DUMMY_PASSWORD_HASH)
            return None

        row = rows[0]
        if not verify_account_password(creds.password, str(row["password_hash"])):
            return None
        return _row_to_account(row)

    async def get_by_id(self, account_id: str) -> Account | None:
        rows = await self._graph.read(FIND_ACCOUNT_BY_ID_CYPHER, {"account_id": account_id})
        return _row_to_account(rows[0]) if rows else None
