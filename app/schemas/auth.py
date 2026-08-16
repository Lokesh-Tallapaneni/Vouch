"""Authentication wire contract."""

from __future__ import annotations

from datetime import datetime

from pydantic import EmailStr, Field

from app.models.account import MIN_PASSWORD_LENGTH
from app.schemas.common import SchemaBase


class RegisterRequest(SchemaBase):
    """Sign-up body."""

    email: EmailStr = Field(description="Sign-in address.", examples=["lokesh@example.com"])
    password: str = Field(
        min_length=MIN_PASSWORD_LENGTH,
        max_length=200,
        description=f"At least {MIN_PASSWORD_LENGTH} characters. Length beats character classes.",
        examples=["correct horse battery staple"],
    )
    person_id: str = Field(
        description="Which existing person in the network this account speaks for.",
        examples=["p0042"],
    )


class LoginRequest(SchemaBase):
    """Sign-in body."""

    email: EmailStr = Field(description="Sign-in address.", examples=["lokesh@example.com"])
    password: str = Field(
        description="The account password.", examples=["correct horse battery staple"]
    )


class AccountResponse(SchemaBase):
    """A signed-in account.

    Deliberately has no password field of any kind. The service hands over an
    Account that came from a row carrying `password_hash`; because this schema
    does not declare it, it cannot be serialised out.
    """

    id: str = Field(description="Account identifier.", examples=["3f2a…"])
    email: str = Field(description="Sign-in address.", examples=["lokesh@example.com"])
    person_id: str = Field(description="The person this account speaks for.", examples=["p0042"])
    created_at: datetime = Field(description="When the account was created.")
