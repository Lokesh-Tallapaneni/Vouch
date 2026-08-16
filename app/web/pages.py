"""Server-rendered pages.

Full-page renders only; htmx partials live in fragments.py. Pages call
services directly rather than HTTP-ing this app's own JSON API -- the API
exists for external clients, not as a detour for the templates that live in
the same process.

Every read page works signed out: ``ViewerId``/``CurrentAccount`` fall back to
the seeded protagonist, so browsing never demands an account. Only the
profile edit form -- the app's single write surface -- requires one, and it
redirects to sign-in rather than 401ing: a browser navigation that hits a
wall should land on a page, not a JSON error. The API path returns 401; the
HTML path redirects. Same rule, two audiences.
"""

from __future__ import annotations

from typing import Annotated, TypedDict

from pydantic import ValidationError
from veloce import Form, RedirectResponse, Request, Response, Router

from app.api.dependencies import (
    AccountServiceDep,
    CurrentAccount,
    NetworkServiceDep,
    PersonServiceDep,
    ReferralServiceDep,
    RequiredAccount,
    SettingsDep,
    ViewerId,
)
from app.core.exceptions import ResourceNotFoundError
from app.core.security import SESSION_COOKIE_NAME, issue_session_token
from app.models.account import Account, AccountCreate, Credentials, SessionClaims
from app.models.person import ProfileUpdate
from app.services.account_service import EmailAlreadyRegisteredError
from app.web.templating import templates

router = Router(tags=["web"])

#: Rendered as clickable chips on the landing page so a non-technical evaluator
#: gets somewhere interesting in one click without having to know a single name.
SUGGESTED_COMPANIES = ["Everline", "Aeromark", "Dunlin Systems", "Halcyon Media"]

#: Must match CSRFMiddleware's own default (app.main, `CSRFMiddleware()` with
#: no override) -- there is no shared constant to import without touching
#: app.main, so this is duplicated and named here deliberately rather than
#: left as a bare string literal at each call site. See the Task 19 report.
CSRF_COOKIE_NAME = "csrf_token"

#: `Annotated[str, Form("")]` rather than the bare `field: str = Form("")`
#: the veloce docs example uses: `Form` (like `Query`/`Path`/`Body`) is a
#: plain class with no mypy-facing return-type trick (no plugin, no
#: `@overload` lying that it returns `str`), so a bare default makes
#: `mypy --strict` reject every one of these signatures with "incompatible
#: default". Moving the marker into `Annotated`'s metadata slot -- the same
#: PEP 593 form `app.api.dependencies` already uses for `Depends(...)` --
#: keeps the parameter's real static type as `str` and hands `Form("")`
#: to veloce only, which reads markers out of `Annotated.__metadata__` (see
#: veloce's `_handler_plan.py`) exactly as it does the bare-default form.
OptionalFormField = Annotated[str, Form("")]

_SESSION_COOKIE_MAX_AGE_SECONDS = 24 * 60 * 60


class _CookieFlags(TypedDict):
    """Mirrors app.api.v1.auth's own `_CookieFlags`/`_COOKIE_FLAGS` exactly --
    that pair is private to its module (leading underscore) and pulling it
    in would reach across a layer boundary for five lines, so it is
    duplicated here instead of shared. A real seam, flagged in the Task 19
    report, not a decision made lightly: if the session cookie's flags ever
    change, both places need the same edit. The `TypedDict` (rather than a
    plain `dict[str, object]`) is what lets `**_SESSION_COOKIE_FLAGS` type-
    check against `Response.set_cookie`'s keyword-specific signature at all --
    confirmed by mypy rejecting the looser dict form here, the same way it
    would in auth.py without this."""

    path: str
    httponly: bool
    secure: bool
    samesite: str


_SESSION_COOKIE_FLAGS: _CookieFlags = {
    "path": "/",
    "httponly": True,
    "secure": True,
    "samesite": "lax",
}


def _attach_session(response: Response, account: Account, secret: str) -> None:
    """Set the session cookie on a web-layer response, in place.

    Deliberately not shared with app.api.v1.auth's `_attach_session` -- see
    `_SESSION_COOKIE_FLAGS` above for why.
    """
    response.set_cookie(
        SESSION_COOKIE_NAME,
        issue_session_token(
            SessionClaims(account_id=account.id, person_id=account.person_id), secret
        ),
        max_age=_SESSION_COOKIE_MAX_AGE_SECONDS,
        **_SESSION_COOKIE_FLAGS,
    )


def _csrf_token(request: Request) -> str:
    """The CSRF cookie CSRFMiddleware has already minted for this browser.

    Read directly from the request rather than through a dependency: this
    value only needs to round-trip into a hidden form field, not drive any
    decision, and CSRFMiddleware itself already re-validates it on submit --
    this is convenience, not a second security check. Empty on a request
    that has genuinely never carried the cookie before (a cold first-ever
    hit landing directly on a form page); in that case the resulting
    hidden field is blank and the following submit correctly fails
    CSRFMiddleware's check rather than silently succeeding, because
    normal browsing always visits at least one page (this cookie is minted
    on every response, safe or not) before reaching a form.
    """
    return request.cookies.get(CSRF_COOKIE_NAME, "")


@router.get("/")
async def show_landing(request: Request, account: CurrentAccount) -> Response:
    """Two ways in: find a route to a person, or reach into a company."""
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "current_account": account, "suggestions": SUGGESTED_COMPANIES},
    )


@router.get("/people/{person_id}")
async def show_person(
    request: Request,
    person_id: str,
    people: PersonServiceDep,
    referrals: ReferralServiceDep,
    viewer_id: ViewerId,
    account: CurrentAccount,
) -> Response:
    """One person: who they are, where they've worked, and your route to them.

    The route is fetched here rather than lazily so the page is complete on
    first paint; the fragment endpoint exists for re-querying at a different
    hop count, not for the initial render. Skipped entirely when viewing
    your own profile -- "your route to yourself" has no meaningful answer.
    """
    profile = await people.get_profile(person_id, viewer_id=viewer_id)
    is_self = person_id == viewer_id
    routes = (
        [] if is_self else await referrals.find_routes(viewer_id, person_id, max_hops=5, limit=5)
    )
    return templates.TemplateResponse(
        "person.html",
        {
            "request": request,
            "current_account": account,
            "profile": profile,
            "routes": routes,
            "max_hops": 5,
            "viewer_id": viewer_id,
            "is_self": is_self,
        },
    )


@router.get("/companies/{company_name}")
async def show_company(
    request: Request,
    company_name: str,
    referrals: ReferralServiceDep,
    viewer_id: ViewerId,
    account: CurrentAccount,
    max_hops: int = 4,
) -> Response:
    """The centrepiece: insiders at this company, ranked by route confidence."""
    insiders = await referrals.find_company_insiders(
        viewer_id, company_name, max_hops=max_hops, limit=10
    )
    return templates.TemplateResponse(
        "company.html",
        {
            "request": request,
            "current_account": account,
            "company": company_name,
            "insiders": insiders,
            "max_hops": max_hops,
        },
    )


@router.get("/network")
async def show_network(
    request: Request, network: NetworkServiceDep, account: CurrentAccount
) -> Response:
    """Network health: brokers and bus-factor risks."""
    return templates.TemplateResponse(
        "network.html",
        {
            "request": request,
            "current_account": account,
            "brokers": await network.find_brokers(limit=15),
            "risks": await network.find_bus_factor_risks(limit=25),
        },
    )


@router.get("/sign-in")
async def show_sign_in(request: Request) -> Response:
    return templates.TemplateResponse(
        "sign_in.html",
        {
            "request": request,
            "current_account": None,
            "error": None,
            "csrf_token": _csrf_token(request),
        },
    )


@router.post("/sign-in")
async def submit_sign_in(
    request: Request,
    accounts: AccountServiceDep,
    settings: SettingsDep,
    email: OptionalFormField,
    password: OptionalFormField,
) -> Response:
    """Exchange credentials for a session cookie, or re-render with an error.

    Calls AccountService directly rather than the JSON API: /api/v1/auth/login
    only accepts a JSON body, and a plain HTML <form> cannot send one without
    JavaScript this app otherwise has no need for. See the Task 19 report.
    """
    try:
        credentials = Credentials(email=email, password=password)
    except ValidationError:
        return templates.TemplateResponse(
            "sign_in.html",
            {
                "request": request,
                "current_account": None,
                "error": "Enter a valid email and password.",
                "csrf_token": _csrf_token(request),
            },
            status_code=422,
        )

    account = await accounts.authenticate(credentials)
    if account is None:
        return templates.TemplateResponse(
            "sign_in.html",
            {
                "request": request,
                "current_account": None,
                "error": "Those credentials didn't match.",
                "csrf_token": _csrf_token(request),
            },
            status_code=401,
        )

    response = RedirectResponse(f"/people/{account.person_id}", status_code=303)
    _attach_session(response, account, settings.jwt_secret.get_secret_value())
    return response


@router.get("/sign-up")
async def show_sign_up(request: Request) -> Response:
    return templates.TemplateResponse(
        "sign_up.html",
        {
            "request": request,
            "current_account": None,
            "error": None,
            "csrf_token": _csrf_token(request),
        },
    )


@router.post("/sign-up")
async def submit_sign_up(
    request: Request,
    accounts: AccountServiceDep,
    settings: SettingsDep,
    person_id: OptionalFormField,
    email: OptionalFormField,
    password: OptionalFormField,
) -> Response:
    """Claim an existing person in the seeded network and sign in as them.

    Sign-up does not create a new Person -- see AccountService.register: the
    graph is the dataset, and a person with no seeded connections would have
    no routes and nothing to show.
    """
    try:
        data = AccountCreate(email=email, password=password, person_id=person_id)
    except ValidationError as exc:
        return templates.TemplateResponse(
            "sign_up.html",
            {
                "request": request,
                "current_account": None,
                "error": exc.errors()[0]["msg"],
                "csrf_token": _csrf_token(request),
            },
            status_code=422,
        )

    try:
        account = await accounts.register(data)
    except (EmailAlreadyRegisteredError, ResourceNotFoundError) as exc:
        return templates.TemplateResponse(
            "sign_up.html",
            {
                "request": request,
                "current_account": None,
                "error": exc.user_message,
                "csrf_token": _csrf_token(request),
            },
            status_code=exc.status_code,
        )

    response = RedirectResponse(f"/people/{account.person_id}", status_code=303)
    _attach_session(response, account, settings.jwt_secret.get_secret_value())
    return response


@router.get("/profile")
async def show_profile_edit(
    request: Request, account: CurrentAccount, people: PersonServiceDep
) -> Response:
    """The edit form for your own profile.

    Redirects rather than 401s: see the module docstring.
    """
    if account is None:
        return RedirectResponse("/sign-in", status_code=303)
    profile = await people.get_profile(account.person_id, viewer_id=account.person_id)
    return templates.TemplateResponse(
        "profile_edit.html",
        {
            "request": request,
            "current_account": account,
            "profile": profile,
            "errors": {},
            "csrf_token": _csrf_token(request),
        },
    )


@router.post("/profile")
async def submit_profile_edit(
    request: Request,
    account: RequiredAccount,
    people: PersonServiceDep,
    name: OptionalFormField,
    title: OptionalFormField,
    seniority: OptionalFormField,
    headline: OptionalFormField,
) -> Response:
    """Apply a profile edit, then redirect.

    POST-then-redirect, so a refresh after saving does not resubmit the form.
    Blank fields are dropped rather than sent as empty strings: an untouched
    input must not blank the stored value.
    """
    submitted = {
        key: value.strip()
        for key, value in (
            ("name", name),
            ("title", title),
            ("seniority", seniority),
            ("headline", headline),
        )
        if value.strip()
    }
    try:
        update = ProfileUpdate.model_validate(submitted)
        await people.update_profile(account.person_id, update)
    except ValidationError as exc:
        profile = await people.get_profile(account.person_id, viewer_id=account.person_id)
        return templates.TemplateResponse(
            "profile_edit.html",
            {
                "request": request,
                "current_account": account,
                "profile": profile,
                "errors": {str(e["loc"][0]): e["msg"] for e in exc.errors()},
                "csrf_token": _csrf_token(request),
            },
            status_code=422,
        )
    return RedirectResponse(f"/people/{account.person_id}", status_code=303)
