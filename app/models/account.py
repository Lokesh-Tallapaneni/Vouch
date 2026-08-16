"""Account and credential models.

An Account is a login. A Person is a node in the professional graph. They are
separate on purpose: most people in the graph will never have an account, and
an account without that separation would force every seeded person to become a
user.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

#: Below this, a passphrase is trivially brute-forced. Length beats character
#: classes, so this is the only rule we impose.
MIN_PASSWORD_LENGTH = 10


class AccountCreate(BaseModel):
    """Sign-up payload."""

    email: EmailStr
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=200)
    person_id: str

    @field_validator("email")
    @classmethod
    def _normalise(cls, value: str) -> str:
        return value.strip().lower()


class Credentials(BaseModel):
    """Sign-in payload. No length floor -- an old password must still verify."""

    email: EmailStr
    password: str

    @field_validator("email")
    @classmethod
    def _normalise(cls, value: str) -> str:
        return value.strip().lower()


class Account(BaseModel):
    """A stored account. Never carries the password hash out of the db layer.

    ``created_at`` expects a native ``datetime``, not a driver temporal or a
    Cypher string dump -- that coercion happens once, at the database boundary
    in :mod:`app.db.client`, not here. See that module for why.
    """

    id: str
    email: str
    person_id: str
    created_at: datetime


class SessionClaims(BaseModel):
    """What the session cookie asserts."""

    account_id: str
    person_id: str
