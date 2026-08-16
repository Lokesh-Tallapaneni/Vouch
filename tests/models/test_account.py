from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.account import Account, AccountCreate


def test_account_create_rejects_a_malformed_email() -> None:
    with pytest.raises(ValidationError):
        AccountCreate(email="not-an-email", password="correct horse battery", person_id="me")


def test_account_create_rejects_a_short_password() -> None:
    with pytest.raises(ValidationError):
        AccountCreate(email="a@b.com", password="short", person_id="me")


def test_account_create_lowercases_the_email() -> None:
    account = AccountCreate(email="A@B.COM", password="correct horse battery", person_id="me")
    assert account.email == "a@b.com"


def test_created_at_accepts_neo4j_nanosecond_precision() -> None:
    account = Account(
        id="a",
        email="a@b.com",
        person_id="me",
        created_at="2026-08-16T10:00:00.123456789+00:00",
    )
    assert account.created_at.year == 2026
