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

from dataclasses import dataclass
from typing import Annotated, TypedDict

from pydantic import ValidationError
from veloce import Form, RedirectResponse, Request, Response, Router

from app.api.dependencies import (
    AccountServiceDep,
    CurrentAccount,
    CurrentAccountName,
    PersonServiceDep,
    ReferralServiceDep,
    RequiredAccount,
    SearchServiceDep,
    SettingsDep,
    ViewerId,
)
from app.core.exceptions import ResourceNotFoundError
from app.core.security import SESSION_COOKIE_NAME, issue_session_token
from app.models.account import Account, AccountCreate, Credentials, SessionClaims
from app.models.person import PersonProfile, ProfileUpdate
from app.models.referral import CompanyInsider, IntroductionRoute
from app.services.account_service import EmailAlreadyRegisteredError
from app.services.person_service import PersonService
from app.web.templating import templates

router = Router(tags=["web"])


@dataclass(frozen=True, slots=True)
class _CompanyInsight:
    """The one sentence a company page leads with -- see _company_insight."""

    headline: str
    detail: str


def _company_insight(
    company: str, insiders: list[CompanyInsider], max_hops: int
) -> _CompanyInsight | None:
    """The one finding grouping insiders by first hop doesn't cover: a
    network that barely reaches this company at all.

    No new query -- reads only the insiders the page already fetched. Used
    to also name the intermediary who shows up on the most routes ("8 of
    10 routes go through Lucas Bhat"), when most of a company's routes ran
    through the same person -- superseded by grouping insiders by
    ``route.hop_details[0].to_name`` directly on the page (see
    ``_group_insiders_by_first_hop``): a group header ("Ask Lucas Bhat ·
    8 people") states that fact structurally, so restating it in prose
    here would say the same thing twice.

    What's left is the case grouping can't express: the *best* route
    already sits at the hop ceiling, or its own confidence is in the weak
    band. Saying that plainly beats a list of near-identical weak numbers
    that just reads as broken -- Cadence Retail's ten routes cluster at
    0.20-0.37 through a single four-hop path, and without this sentence
    that page looks like a bug report, not an answer.
    """
    if not insiders:
        return None

    # COMPANY_INSIDERS_CYPHER already orders by confidence DESC, so the
    # first row is the best route this company has to offer.
    best = insiders[0]
    if best.route.hops >= max_hops or best.route.confidence < 0.4:
        hops = best.route.hops
        return _CompanyInsight(
            headline=f"Your network barely reaches {company}.",
            detail=(
                f"The best route is {hops} introduction{'' if hops == 1 else 's'} "
                "long, which rarely gets a reply."
            ),
        )
    return None


@dataclass(frozen=True, slots=True)
class _InsiderGroup:
    """Everyone reachable through the same first hop out of the viewer,
    plus the one edge every route in the group shares.

    Every route in this app starts at the viewer (find_company_insiders
    takes viewer_id as its start node), so ``trunk`` -- the "you -> asker"
    edge -- is identical for every member of the group: it's the same
    relationship in the graph, read off any one of them. Drawing it once
    on the page instead of once per person is the entire point of
    grouping -- see _group_insiders_by_first_hop.
    """

    asker_name: str
    trunk: IntroductionRoute
    insiders: list[CompanyInsider]


def _group_insiders_by_first_hop(insiders: list[CompanyInsider]) -> list[_InsiderGroup]:
    """Group insiders by the person you'd actually message, not the target.

    ``route.hop_details[0].to_name`` -- the first hop out of the viewer --
    is the only decision a reader makes on this page (who to ask), so it's
    the organising principle rather than a count buried in a banner. An
    insider one hop from the viewer is their own asker
    (``hop_details[0].to_name == insider.name``): there's no intermediary
    to name, you just reach out directly, and the resulting group of one
    still has to render correctly ("Ask Priya Sharma · 1 person").

    Groups come back largest first -- the point of grouping is exactly the
    fact the old insight banner used to spell out in prose ("8 of 10
    routes go through X"); sorting by size makes that structural instead
    of textual. Python's sort is stable, so ties keep the incoming order,
    which is already confidence-descending (COMPANY_INSIDERS_CYPHER's own
    ordering) -- the same tiebreak the old flat list used.

    Grouping happens here, not in the template: ``route.hop_details[0]``
    reached from Jinja is exactly the kind of nested-attribute-inside-a-
    groupby the language handles awkwardly, and pages.py already shapes
    every other piece of data this page renders.
    """
    order: list[str] = []
    buckets: dict[str, list[CompanyInsider]] = {}
    for insider in insiders:
        asker = insider.route.hop_details[0].to_name
        if asker not in buckets:
            buckets[asker] = []
            order.append(asker)
        buckets[asker].append(insider)

    groups = [
        _InsiderGroup(
            asker_name=name,
            # A genuine 1-hop route from the viewer to the asker: its
            # confidence is honestly just that one edge's strength, since a
            # single-hop route's confidence is the product of one number.
            trunk=IntroductionRoute(
                chain=[members[0].route.hop_details[0].from_name, name],
                hops=1,
                confidence=members[0].route.hop_details[0].strength,
                hop_details=[members[0].route.hop_details[0]],
            ),
            insiders=members,
        )
        for name, members in ((name, buckets[name]) for name in order)
    ]
    groups.sort(key=lambda group: len(group.insiders), reverse=True)
    return groups


#: How many suggestion chips the landing page offers. Four fits one row at
#: every width the design supports; the names themselves come from the graph
#: (SearchService.suggest_companies), not from a list written down here.
SUGGESTED_COMPANY_COUNT = 4

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


async def _attach_session(
    response: Response, account: Account, people: PersonService, secret: str
) -> None:
    """Set the session cookie on a web-layer response, in place.

    Deliberately not shared with app.api.v1.auth's `_attach_session` -- see
    `_SESSION_COOKIE_FLAGS` above for why -- which means it independently
    needs the same fix that module's version has: the token carries the
    account holder's display name (one lookup, here, at sign-in) so
    `get_current_account_name` reads it for free on every page after this
    one, instead of paying a database call on each. A user signing in
    through this form must get a token identical in shape to one from the
    JSON API -- see `SessionClaims`' own docstring for the staleness
    trade-off that comes with it.
    """
    name = await people.get_display_name(account.person_id)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        issue_session_token(
            SessionClaims(account_id=account.id, person_id=account.person_id, name=name), secret
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
async def show_landing(
    request: Request,
    search: SearchServiceDep,
    viewer_id: ViewerId,
    account: CurrentAccount,
    display_name: CurrentAccountName,
) -> Response:
    """Two ways in: find a route to a person, or reach into a company.

    The company chips are queried per viewer rather than hardcoded. They used
    to be a literal list of four names, which is a hardcoded answer to a
    question the graph can answer -- and the wrong answer for anyone whose
    connections lie elsewhere. `suggest_companies` ranks by how many people
    the viewer knows within two hops, so the first chip is genuinely their
    best way in.
    """
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "current_account": account,
            "current_account_name": display_name,
            "suggestions": await search.suggest_companies(viewer_id, limit=SUGGESTED_COMPANY_COUNT),
        },
    )


@router.get("/people/{person_id}")
async def show_person(
    request: Request,
    person_id: str,
    people: PersonServiceDep,
    referrals: ReferralServiceDep,
    viewer_id: ViewerId,
    account: CurrentAccount,
    display_name: CurrentAccountName,
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
    # submit_sign_in/submit_sign_up redirect here with ?signed_in=1 on
    # success -- signing in genuinely changes every answer on this site
    # (the viewer the whole graph is walked from), and nothing said so
    # without this. A query flag rather than session state: stateless,
    # survives a refresh as "still just signed in" for exactly one load,
    # and needs no new storage.
    just_signed_in = (
        is_self and account is not None and request.query_params.get("signed_in") == "1"
    )
    return templates.TemplateResponse(
        "person.html",
        {
            "request": request,
            "current_account": account,
            "current_account_name": display_name,
            "profile": profile,
            "routes": routes,
            "max_hops": 5,
            "viewer_id": viewer_id,
            "is_self": is_self,
            "just_signed_in": just_signed_in,
        },
    )


@router.get("/companies/{company_name}")
async def show_company(
    request: Request,
    company_name: str,
    referrals: ReferralServiceDep,
    viewer_id: ViewerId,
    account: CurrentAccount,
    display_name: CurrentAccountName,
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
            "current_account_name": display_name,
            "company": company_name,
            "insiders": insiders,
            "groups": _group_insiders_by_first_hop(insiders),
            "max_hops": max_hops,
            "insight": _company_insight(company_name, insiders, max_hops),
        },
    )


@router.get("/network")
async def show_network(
    request: Request, account: CurrentAccount, display_name: CurrentAccountName
) -> Response:
    """Network health shell: brokers and bus-factor risks load lazily via
    htmx (see fragments.py's brokers_fragment/bus_factor_risks_fragment).

    Brokers alone runs ~3.9s against the live instance -- fetching it here,
    before returning a response at all, would leave the browser painting
    nothing for that whole time. Rendering the shell immediately and letting
    each panel hx-get itself is what keeps this page from reading as hung.
    """
    return templates.TemplateResponse(
        "network.html",
        {"request": request, "current_account": account, "current_account_name": display_name},
    )


#: Shown on /sign-in when a redirect got you there instead of a link --
#: keyed by the `reason` query param each redirect sets, so a silent bounce
#: (visit /profile signed out, land on /sign-in with no explanation) always
#: says why. New callers just need a new key here and `?reason=<key>` on
#: their own redirect.
_SIGN_IN_REASONS: dict[str, str] = {
    "profile": "Sign in to edit your profile.",
}


@router.get("/sign-in")
async def show_sign_in(request: Request) -> Response:
    return templates.TemplateResponse(
        "sign_in.html",
        {
            "request": request,
            "current_account": None,
            "current_account_name": None,
            "error": None,
            "notice": _SIGN_IN_REASONS.get(request.query_params.get("reason", "")),
            "csrf_token": _csrf_token(request),
        },
    )


@router.post("/sign-in")
async def submit_sign_in(
    request: Request,
    accounts: AccountServiceDep,
    people: PersonServiceDep,
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
                "current_account_name": None,
                "error": "Enter a valid email and password.",
                "notice": None,
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
                "current_account_name": None,
                "error": "Those credentials didn't match.",
                "notice": None,
                "csrf_token": _csrf_token(request),
            },
            status_code=401,
        )

    # ?signed_in=1 -- see show_person's just_signed_in: signing in changes
    # every route on the site (the viewer the whole graph walks from), and
    # this is what confirms that instead of leaving it implicit.
    response = RedirectResponse(f"/people/{account.person_id}?signed_in=1", status_code=303)
    await _attach_session(response, account, people, settings.jwt_secret.get_secret_value())
    return response


async def _redisplay_selection(people: PersonService, person_id: str) -> PersonProfile | None:
    """Re-fetch a claimed person for error redisplay, so a rejected sign-up
    (weak password, taken email) doesn't discard a selection the user
    already made via the name search below -- see submit_sign_up.
    """
    if not person_id:
        return None
    try:
        return await people.get_profile(person_id, viewer_id=None)
    except ResourceNotFoundError:
        return None


@router.get("/sign-up")
async def show_sign_up(request: Request) -> Response:
    return templates.TemplateResponse(
        "sign_up.html",
        {
            "request": request,
            "current_account": None,
            "current_account_name": None,
            "error": None,
            "email": "",
            "selected": None,
            "csrf_token": _csrf_token(request),
        },
    )


@router.post("/sign-up")
async def submit_sign_up(
    request: Request,
    accounts: AccountServiceDep,
    people: PersonServiceDep,
    settings: SettingsDep,
    person_id: OptionalFormField,
    email: OptionalFormField,
    password: OptionalFormField,
) -> Response:
    """Claim an existing person in the seeded network and sign in as them.

    Sign-up does not create a new Person -- see AccountService.register: the
    graph is the dataset, and a person with no seeded connections would have
    no routes and nothing to show. `person_id` arrives from the name-search
    claim widget (_claim_block.html / fragments.claim_select_fragment), not
    typed by hand -- a database primary key is not something a non-technical
    person can supply, and the assignment brief requires exactly that kind
    of person to be able to use this app.
    """
    try:
        data = AccountCreate(email=email, password=password, person_id=person_id)
    except ValidationError as exc:
        return templates.TemplateResponse(
            "sign_up.html",
            {
                "request": request,
                "current_account": None,
                "current_account_name": None,
                "error": exc.errors()[0]["msg"],
                "email": email,
                "selected": await _redisplay_selection(people, person_id),
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
                "current_account_name": None,
                "error": exc.user_message,
                "email": email,
                "selected": await _redisplay_selection(people, person_id),
                "csrf_token": _csrf_token(request),
            },
            status_code=exc.status_code,
        )

    response = RedirectResponse(f"/people/{account.person_id}?signed_in=1", status_code=303)
    await _attach_session(response, account, people, settings.jwt_secret.get_secret_value())
    return response


@router.post("/sign-out")
async def submit_sign_out(request: Request) -> Response:
    """Clear the session cookie and redirect home -- via a response header,
    not client-side script.

    `_header.html`'s sign-out button used to POST straight to the JSON API's
    `/api/v1/auth/logout` and rely on `hx-on::after-request` to redirect
    afterwards. htmx compiles `hx-on` handlers through `new Function()`,
    which this app's CSP (`script-src 'self'`, no `unsafe-eval`) blocks: the
    POST succeeded and the cookie was cleared, but the eval threw silently,
    so the redirect never fired -- a signed-out user kept seeing their own
    email in the header until a manual reload. `HX-Redirect` is a response
    header htmx honours natively, with no script execution at all, so this
    is a dedicated web-layer route (same reasoning as submit_sign_in) rather
    than weakening the CSP for one button.
    """
    response = Response(status_code=204, headers={"HX-Redirect": "/"})
    response.delete_cookie(SESSION_COOKIE_NAME, **_SESSION_COOKIE_FLAGS)
    return response


@router.get("/profile")
async def show_profile_edit(
    request: Request, account: CurrentAccount, people: PersonServiceDep
) -> Response:
    """The edit form for your own profile.

    Redirects rather than 401s: see the module docstring. `?reason=profile`
    is what lets /sign-in explain *why* the redirect happened instead of
    bouncing a signed-out visitor there silently -- see _SIGN_IN_REASONS.
    """
    if account is None:
        return RedirectResponse("/sign-in?reason=profile", status_code=303)
    profile = await people.get_profile(account.person_id, viewer_id=account.person_id)
    return templates.TemplateResponse(
        "profile_edit.html",
        {
            "request": request,
            "current_account": account,
            # profile.name is the signed-in account holder's own name here
            # (person_id == account.person_id), so this reuses the fetch
            # above rather than calling CurrentAccountName for a second one.
            "current_account_name": profile.name,
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
                "current_account_name": profile.name,
                "profile": profile,
                "errors": {str(e["loc"][0]): e["msg"] for e in exc.errors()},
                "csrf_token": _csrf_token(request),
            },
            status_code=422,
        )
    return RedirectResponse(f"/people/{account.person_id}", status_code=303)
