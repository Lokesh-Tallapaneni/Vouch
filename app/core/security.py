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

from veloce import JWTError, decode_jwt, encode_jwt, hash_password, verify_password

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
    corrupted row into a 500 here. Because `verify_password` documents that it
    never raises, there is no enumerable set of exception types to narrow this
    to -- unlike `read_session_token` below, this stays a broad catch on
    purpose, logged so it is visible rather than silent if it is ever hit.
    """
    try:
        return bool(verify_password(hashed, raw))
    except Exception as exc:  # noqa: BLE001 -- any failure here is simply "no match"
        # A warning, not debug/info: reaching this branch at all means a
        # stored hash didn't parse, which points at data corruption an
        # operator wants to know about -- unlike an ordinary bad password.
        log.warning("stored password hash could not be verified: %s", type(exc).__name__)
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
    unlisted algorithm, malformed input, missing/mistyped claims. Callers
    treat None as "signed out" and never as an error, so a stale cookie can
    never 500 a page.

    Catches `JWTError` specifically, not `Exception`: that is the complete,
    enumerable hierarchy `decode_jwt` raises for every way a *token* can be
    untrustworthy (bad signature, expiry, unsupported algorithm, malformed
    segments, missing claims -- see `veloce.security.jwt`). It does not catch
    the plain `ValueError` `decode_jwt` raises for an empty algorithms
    allow-list or an empty secret, which Veloce raises loudly on purpose:
    those describe a misconfigured caller, not an untrustworthy token, and
    silently downgrading that to "signed out" would hide a real bug (e.g. an
    empty JWT secret) behind an ordinary-looking logged-out state.
    """
    try:
        payload = decode_jwt(token, secret, algorithms=[_ALGORITHM])
    except JWTError as exc:
        # Never log the token or secret -- the token is a bearer credential.
        # The exception type is enough to debug a real problem without it.
        log.info("session token rejected: %s", type(exc).__name__)
        return None

    account_id, person_id = payload.get("sub"), payload.get("pid")
    if not isinstance(account_id, str) or not isinstance(person_id, str):
        log.info("session token rejected: missing or mistyped claims")
        return None
    return SessionClaims(account_id=account_id, person_id=person_id)
