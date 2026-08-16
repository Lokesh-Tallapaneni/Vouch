from __future__ import annotations

import logging
from dataclasses import dataclass

import pytest
from neo4j.exceptions import ConstraintError

from app.core.exceptions import ResourceNotFoundError
from app.core.security import hash_account_password
from app.models.account import AccountCreate, Credentials
from app.services.account_service import AccountService, EmailAlreadyRegisteredError
from tests.support.fake_graph import FakeGraph

CREATED = "2026-08-16T10:00:00Z"


@dataclass
class _ConstraintViolatingGraph(FakeGraph):
    """A FakeGraph whose write() raises like a real constraint violation.

    Simulates the loser of a concurrent registration race: the database
    itself rejects the second MERGE for an email already claimed, rather than
    the service's own (inherently racy) pre-check ever seeing it.
    """

    async def write(
        self, cypher: str, params: dict[str, object] | None = None, *, timeout: float | None = None
    ) -> list[dict[str, object]]:
        if "MERGE (a:Account" in cypher:
            raise ConstraintError(
                "Node(0) already exists with label `Account` and property `email` = 'a@b.com'"
            )
        return await super().write(cypher, params, timeout=timeout)


def _account_row(email: str = "a@b.com", hashed: str | None = None) -> dict[str, object]:
    return {
        "id": "acc-1",
        "email": email,
        "person_id": "me",
        "created_at": CREATED,
        "password_hash": hashed or hash_account_password("correct horse battery"),
    }


async def test_register_returns_the_created_account() -> None:
    # "RETURN p.id AS id" (PERSON_EXISTS_CYPHER's own clause), not
    # "MATCH (p:Person" -- CREATE_ACCOUNT_CYPHER also MATCHes the person it is
    # attaching the new account to, so that fragment matches both statements
    # and FakeGraph raises AmbiguousFragmentError rather than picking one.
    graph = FakeGraph({"MERGE (a:Account": [_account_row()], "RETURN p.id AS id": [{"id": "me"}]})
    account = await AccountService(graph).register(
        AccountCreate(email="a@b.com", password="correct horse battery", person_id="me")
    )
    assert account.email == "a@b.com" and account.person_id == "me"


async def test_register_never_sends_the_raw_password_to_the_graph() -> None:
    graph = FakeGraph({"MERGE (a:Account": [_account_row()], "RETURN p.id AS id": [{"id": "me"}]})
    await AccountService(graph).register(
        AccountCreate(email="a@b.com", password="correct horse battery", person_id="me")
    )
    for call in graph.calls:
        assert "correct horse battery" not in str(call.params)


async def test_register_rejects_an_unknown_person_id() -> None:
    graph = FakeGraph({"RETURN p.id AS id": []})
    with pytest.raises(ResourceNotFoundError):
        await AccountService(graph).register(
            AccountCreate(email="a@b.com", password="correct horse battery", person_id="ghost")
        )


async def test_register_rejects_an_email_already_in_use() -> None:
    graph = FakeGraph(
        {
            "RETURN p.id AS id": [{"id": "me"}],
            "MATCH (a:Account {email": [_account_row()],
        }
    )
    with pytest.raises(EmailAlreadyRegisteredError):
        await AccountService(graph).register(
            AccountCreate(email="a@b.com", password="correct horse battery", person_id="me")
        )


async def test_authenticate_accepts_correct_credentials() -> None:
    graph = FakeGraph({"MATCH (a:Account {email": [_account_row()]})
    result = await AccountService(graph).authenticate(
        Credentials(email="a@b.com", password="correct horse battery")
    )
    assert result is not None and result.id == "acc-1"


async def test_authenticate_rejects_a_wrong_password() -> None:
    graph = FakeGraph({"MATCH (a:Account {email": [_account_row()]})
    assert (
        await AccountService(graph).authenticate(
            Credentials(email="a@b.com", password="not the password")
        )
        is None
    )


async def test_authenticate_returns_none_for_an_unknown_email() -> None:
    assert (
        await AccountService(FakeGraph({})).authenticate(
            Credentials(email="nobody@b.com", password="whatever passphrase")
        )
        is None
    )


async def test_a_concurrent_duplicate_registration_raises_the_friendly_error_not_a_500() -> None:
    # The pre-check (test_register_rejects_an_email_already_in_use above) is
    # inherently racy -- check-then-write. This is what actually protects a
    # real race: the database's Account.email UNIQUE constraint rejects the
    # losing MERGE, raising neo4j's ConstraintError (a ClientError subclass
    # GraphClient re-raises untranslated) rather than returning rows. Without
    # a handler for it, the loser of that race gets an unhandled 500 while
    # the non-concurrent duplicate gets a friendly 409 -- same user-visible
    # situation, two different outcomes.
    graph = _ConstraintViolatingGraph({"RETURN p.id AS id": [{"id": "me"}]})
    with pytest.raises(EmailAlreadyRegisteredError):
        await AccountService(graph).register(
            AccountCreate(email="a@b.com", password="correct horse battery", person_id="me")
        )


async def test_authenticate_logs_nothing_that_distinguishes_the_two_failure_modes(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Both existing tests above only assert the *return value* is None for
    # each failure mode -- neither would catch a regression that logged, say,
    # `log.warning("unknown email: %s", email)` on only one branch. That would
    # still return None both times while handing an attacker exactly the
    # oracle authenticate() exists to avoid. This asserts on the logs
    # themselves: no record from either branch names either address, and the
    # two branches produce the same *shape* of log output (here: none at all).
    email_with_an_account = "a@b.com"
    email_with_no_account = "nobody@b.com"
    with caplog.at_level(logging.DEBUG):
        graph = FakeGraph({"MATCH (a:Account {email": [_account_row(email_with_an_account)]})
        await AccountService(graph).authenticate(
            Credentials(email=email_with_an_account, password="not the password")
        )
        wrong_password_records = list(caplog.records)
        caplog.clear()

        await AccountService(FakeGraph({})).authenticate(
            Credentials(email=email_with_no_account, password="whatever passphrase")
        )
        unknown_email_records = list(caplog.records)

    for records in (wrong_password_records, unknown_email_records):
        for record in records:
            message = record.getMessage()
            assert email_with_an_account not in message
            assert email_with_no_account not in message

    wrong_password_shape = [(r.levelno, r.name) for r in wrong_password_records]
    unknown_email_shape = [(r.levelno, r.name) for r in unknown_email_records]
    assert wrong_password_shape == unknown_email_shape
