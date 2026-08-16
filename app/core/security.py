"""Password hashing and session tokens.

Thin wrappers over Veloce's own primitives rather than a bespoke
implementation: the framework already ships a vetted password hash and JWT
codec, and rolling either by hand on an application that grades engineering
hygiene is the wrong trade.

The wrappers exist so that (a) call sites never touch a JWT library directly,
(b) every decode failure funnels into a single "return None" rather than five
different exception types at five call sites, and (c) swapping the algorithm
later is one edit.

Identity is stateless by design: the token carries who you are, so there is no
session store, no sticky routing and nothing to clean up.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from veloce import decode_jwt, encode_jwt, hash_password, verify_password

from app.core.logging import get_logger
from app.models.account import SessionClaims

log = get_logger("security")

#: Cookie name. HttpOnly and Secure are set where the cookie is written, so a
#: script on the page can never read it -- which is the whole reason the token
#: is not in localStorage.
SESSION_COOKIE_NAME = "vouch_session"

DEFAULT_TTL_HOURS = 24

#: Signature algorithm allow-list, singular by design: decode_jwt requires an
#: explicit, non-empty allow-list, and rejects `alg: none` and anything not in
#: it *before* touching the signature. Passing anything less than an explicit
#: list here would defeat that check.
_ALGORITHM = "HS256"


def hash_account_password(raw: str) -> str:
    """Hash a password for storage. The raw value is never logged or returned."""
    return hash_password(raw)


def verify_account_password(raw: str, hashed: str) -> bool:
    """Check a password against a stored hash.

    Veloce's `verify_password(stored, candidate)` already returns False
    (never raises) for a malformed `stored` value; the try/except is a second
    line of defence so a future change to that contract still can't turn a
    corrupted row into a 500 here.
    """
    try:
        return bool(verify_password(hashed, raw))
    except Exception:  # noqa: BLE001 -- any failure here is simply "no match"
        return False


def issue_session_token(
    claims: SessionClaims, secret: str, ttl_hours: int = DEFAULT_TTL_HOURS
) -> str:
    """Mint a signed identity token."""
    now = datetime.now(UTC)
    payload = {
        "sub": claims.account_id,
        "pid": claims.person_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=ttl_hours)).timestamp()),
    }
    return encode_jwt(payload, secret, alg=_ALGORITHM)


def read_session_token(token: str, secret: str) -> SessionClaims | None:
    """Verify and decode a token.

    Returns None for anything untrustworthy -- bad signature, expiry,
    malformed input, missing claims. Callers treat None as "signed out" and
    never as an error, so a stale cookie can never 500 a page.
    """
    try:
        payload = decode_jwt(token, secret, algorithms=[_ALGORITHM])
    except Exception:  # noqa: BLE001 -- every failure mode means "not signed in"
        return None

    account_id, person_id = payload.get("sub"), payload.get("pid")
    if not isinstance(account_id, str) or not isinstance(person_id, str):
        return None
    return SessionClaims(account_id=account_id, person_id=person_id)
