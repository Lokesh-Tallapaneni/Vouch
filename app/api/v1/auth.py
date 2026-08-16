"""Authentication endpoints.

The session cookie is set and cleared here and nowhere else, so its flags exist
in exactly one place: `_COOKIE_FLAGS` below, shared by both `set_cookie` and
`delete_cookie`. It is HttpOnly (script cannot read it), Secure (never sent
over plain HTTP) and SameSite=Lax (not attached to cross-site POSTs, which is
the first of the two CSRF defences; the token is the second).

Sharing the flags is not just tidiness: veloce's own `delete_cookie` docstring
warns that a browser only treats a deletion as replacing the original cookie
if Path, Domain, Secure and SameSite all match what it was set with -- a
mismatched clear leaves the original, authenticated cookie alive alongside a
second, harmless one.
"""

from __future__ import annotations

from typing import TypedDict

from veloce import JSONResponse, Response, Router

from app.api.dependencies import AccountServiceDep, CurrentAccount, PersonServiceDep, SettingsDep
from app.core.security import SESSION_COOKIE_NAME, issue_session_token
from app.models.account import Account, AccountCreate, Credentials, SessionClaims
from app.schemas.auth import AccountResponse, LoginRequest, RegisterRequest
from app.schemas.common import AUTH_RESPONSES, ERROR_RESPONSES, ErrorResponse
from app.services.person_service import PersonService

router = Router(prefix="/auth", tags=["auth"])

_COOKIE_MAX_AGE_SECONDS = 24 * 60 * 60


class _CookieFlags(TypedDict):
    """The subset of `Response.set_cookie`/`delete_cookie` keyword arguments
    that must match between the two calls for a deletion to actually replace
    the cookie a login set (see module docstring)."""

    path: str
    httponly: bool
    secure: bool
    samesite: str


#: The one place the cookie's browser-facing attributes are decided. Passed
#: identically to `set_cookie` (below) and `delete_cookie` (in `log_out`).
_COOKIE_FLAGS: _CookieFlags = {
    "path": "/",
    "httponly": True,
    "secure": True,
    "samesite": "lax",
}


async def _attach_session(
    response: Response, account: Account, people: PersonService, secret: str
) -> Response:
    """Set the session cookie, embedding the account holder's display name.

    The one place this costs a database call: once, here, at sign-in --
    not on every subsequent page load. `get_current_account_name`
    (app.api.dependencies) reads the name straight off the token from here
    on, which is the entire point of doing it at mint time instead. A
    lookup that finds nothing (should not happen for a person id that just
    passed `register`/`authenticate`, but nothing here assumes it can't)
    yields `name=None` -- not a failure, just a session that falls back to
    a per-request lookup until its next sign-in, same as a token minted
    before this field existed. See `SessionClaims`' own docstring for why
    a stale name in the meantime is an acceptable trade and nothing more
    than that is ever allowed to ride on this claim.
    """
    name = await people.get_display_name(account.person_id)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        issue_session_token(
            SessionClaims(account_id=account.id, person_id=account.person_id, name=name), secret
        ),
        max_age=_COOKIE_MAX_AGE_SECONDS,
        **_COOKIE_FLAGS,
    )
    return response


@router.post(
    "/register",
    response_model=AccountResponse,
    status_code=201,
    summary="Create an account",
    response_description="The new account. Signs in on success.",
    responses={
        409: {"model": ErrorResponse, "description": "Email already registered."},
        **ERROR_RESPONSES,
    },
)
async def register_account(
    payload: RegisterRequest,
    accounts: AccountServiceDep,
    people: PersonServiceDep,
    settings: SettingsDep,
) -> Response:
    """Create an account and sign the new user straight in."""
    account = await accounts.register(AccountCreate.model_validate(payload.model_dump()))
    response = JSONResponse(account.model_dump(mode="json"), status_code=201)
    return await _attach_session(response, account, people, settings.jwt_secret.get_secret_value())


@router.post(
    "/login",
    response_model=AccountResponse,
    summary="Sign in",
    response_description="The signed-in account. Sets the session cookie.",
    responses=AUTH_RESPONSES,
)
async def log_in(
    payload: LoginRequest,
    accounts: AccountServiceDep,
    people: PersonServiceDep,
    settings: SettingsDep,
) -> Response:
    """Exchange credentials for a session cookie.

    One message for both failure modes, so the endpoint is not an
    account-enumeration oracle.
    """
    account = await accounts.authenticate(Credentials.model_validate(payload.model_dump()))
    if account is None:
        return JSONResponse({"detail": "Those credentials didn't match."}, status_code=401)
    response = JSONResponse(account.model_dump(mode="json"))
    return await _attach_session(response, account, people, settings.jwt_secret.get_secret_value())


@router.post(
    "/logout",
    status_code=204,
    summary="Sign out",
    response_description="Session cookie cleared.",
)
async def log_out() -> Response:
    """Clear the session cookie.

    Deleting the cookie is the whole logout: the token is stateless, so there
    is no server-side session to invalidate. The trade-off -- an already-issued
    token stays valid until it expires -- is bounded by the 24h TTL.
    """
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE_NAME, **_COOKIE_FLAGS)
    return response


@router.get(
    "/session",
    response_model=AccountResponse,
    summary="Who am I",
    response_description="The account the session cookie identifies.",
    responses=AUTH_RESPONSES,
)
async def read_session(account: CurrentAccount) -> Response:
    """Who the caller is, for the UI to render the right header."""
    if account is None:
        return JSONResponse({"detail": "Not signed in."}, status_code=401)
    return JSONResponse(account.model_dump(mode="json"))
