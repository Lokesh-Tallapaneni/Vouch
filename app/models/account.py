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
    """What the session cookie asserts.

    ``name`` is a display convenience, not an authorisation claim, and that
    distinction has to hold for as long as this field exists: it lets
    ``get_current_account_name`` read the signed-in header straight off an
    already-decoded token instead of paying a database round trip on every
    page. The trade-off, named so nobody "fixes" it by adding more to the
    token later: if someone renames themselves via ``PATCH /people/me``, the
    header keeps showing the old name until their next sign-in, since the
    token isn't re-issued on a profile edit. That staleness window is fine
    for a name shown in navigation chrome. It would not be fine for
    anything an authorisation decision depends on -- a role, a permission, a
    revocation flag -- because ``get_current_account`` deliberately re-reads
    those from the graph on every request specifically so a change takes
    effect immediately (see that function's own docstring). ``name`` must
    stay display-only, or that property quietly breaks.

    Optional, not required: a token minted before this field existed (or by
    a code path not yet updated to supply it) still decodes and signs
    someone in -- it just carries no name, and callers fall back to a
    database lookup rather than showing a blank or broken header for that
    session's remaining lifetime.
    """

    account_id: str
    person_id: str
    name: str | None = None
