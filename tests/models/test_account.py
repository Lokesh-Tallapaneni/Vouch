from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.account import AccountCreate


def test_account_create_rejects_a_malformed_email() -> None:
    with pytest.raises(ValidationError):
        AccountCreate(email="not-an-email", password="correct horse battery", person_id="me")


def test_account_create_rejects_a_short_password() -> None:
    with pytest.raises(ValidationError):
        AccountCreate(email="a@b.com", password="short", person_id="me")


def test_account_create_lowercases_the_email() -> None:
    account = AccountCreate(email="A@B.COM", password="correct horse battery", person_id="me")
    assert account.email == "a@b.com"
