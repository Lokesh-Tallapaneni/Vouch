"""Account and credential models.

An Account is a login. A Person is a node in the professional graph. They are
separate on purpose: most people in the graph will never have an account, and
an account without that separation would force every seeded person to become a
user.
"""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

#: Below this, a passphrase is trivially brute-forced. Length beats character
#: classes, so this is the only rule we impose.
MIN_PASSWORD_LENGTH = 10

#: Matches the fractional-seconds component of an ISO-8601 timestamp beyond
#: six digits, capturing the first six so they can be kept and the rest
#: discarded. Whatever follows (an offset like ``+00:00`` or a ``Z``) sits
#: outside the match and is left untouched.
_EXCESS_FRACTIONAL_SECONDS = re.compile(r"(\.\d{6})\d+")


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
    """A stored account. Never carries the password hash out of the db layer."""

    id: str
    email: str
    person_id: str
    created_at: datetime

    @field_validator("created_at", mode="before")
    @classmethod
    def _truncate_neo4j_nanosecond_precision(cls, value: object) -> object:
        """Neo4j's ``toString()`` on a datetime emits 9-digit fractional
        seconds; Python's ISO-8601 parser accepts at most 6. Without this,
        every account read from the graph would fail validation.
        """
        if isinstance(value, str):
            return _EXCESS_FRACTIONAL_SECONDS.sub(r"\1", value)
        return value


class SessionClaims(BaseModel):
    """What the session cookie asserts."""

    account_id: str
    person_id: str
