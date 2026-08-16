from __future__ import annotations

import pytest

from app.core.exceptions import ResourceNotFoundError
from app.core.security import hash_account_password
from app.models.account import AccountCreate, Credentials
from app.services.account_service import AccountService, EmailAlreadyRegisteredError
from tests.support.fake_graph import FakeGraph

CREATED = "2026-08-16T10:00:00Z"


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
