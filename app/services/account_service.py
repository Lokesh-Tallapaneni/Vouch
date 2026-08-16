"""Account registration and authentication.

Services own the translation between result rows and domain models. Nothing
above this layer sees a driver dict, and nothing below it knows what HTTP is.
"""

from __future__ import annotations

import uuid

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


class EmailAlreadyRegisteredError(VouchError):
    """Sign-up used an address that already has an account."""

    status_code = 409
    user_message = "That email address already has an account. Try signing in."


class AccountService:
    def __init__(self, graph: GraphClient) -> None:
        self._graph = graph

    async def register(self, data: AccountCreate) -> Account:
        """Create an account linked to an existing person.

        Sign-up claims an existing person in the seeded network rather than
        creating a new one: the graph is the dataset, and an account with no
        connections would have no routes and nothing to show.

        The pre-check below is a fast path for a friendly error message, not
        the safety mechanism: it is inherently racy (check-then-write). What
        actually makes two simultaneous sign-ups for the same address safe is
        the UNIQUE constraint on ``Account.email`` applied by the migration --
        the losing `MERGE` in a concurrent pair fails at the database rather
        than silently creating a duplicate account.
        """
        if not await self._graph.read(PERSON_EXISTS_CYPHER, {"person_id": data.person_id}):
            raise ResourceNotFoundError("We couldn't find that person in the network.")

        if await self._graph.read(FIND_ACCOUNT_BY_EMAIL_CYPHER, {"email": data.email}):
            raise EmailAlreadyRegisteredError()

        rows = await self._graph.write(
            CREATE_ACCOUNT_CYPHER,
            {
                "account_id": str(uuid.uuid4()),
                "email": data.email,
                "password_hash": hash_account_password(data.password),
                "person_id": data.person_id,
            },
        )
        if not rows:
            raise ResourceNotFoundError("Could not create the account.")
        log.info("registered account for person %s", data.person_id)
        return Account.model_validate(rows[0])

    async def authenticate(self, creds: Credentials) -> Account | None:
        """Verify credentials.

        Returns None for both "no such email" and "wrong password", and logs
        neither the address nor the attempt outcome in a way that distinguishes
        them -- telling an attacker which addresses are registered is a free
        account-enumeration oracle.
        """
        rows = await self._graph.read(FIND_ACCOUNT_BY_EMAIL_CYPHER, {"email": creds.email})
        if not rows:
            return None

        row = rows[0]
        if not verify_account_password(creds.password, str(row["password_hash"])):
            return None
        return Account.model_validate({k: v for k, v in row.items() if k != "password_hash"})

    async def get_by_id(self, account_id: str) -> Account | None:
        rows = await self._graph.read(FIND_ACCOUNT_BY_ID_CYPHER, {"account_id": account_id})
        return Account.model_validate(rows[0]) if rows else None
