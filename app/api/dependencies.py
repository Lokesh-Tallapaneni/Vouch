"""Shared request dependencies.

Routes depend on these rather than reaching into ``request.app.state``
themselves. That indirection is what lets a test swap the graph for a fake with
``app.dependency_overrides[get_graph] = fake_graph`` and never open a socket.

Each dependency is also exported as an ``Annotated`` alias, so handler
signatures read as types rather than as plumbing::

    async def get_person(person_id: str, graph: GraphDep) -> PersonProfile: ...
"""

from __future__ import annotations

from typing import Annotated, cast

from veloce import Depends, HTTPException, Request

from app.core.security import SESSION_COOKIE_NAME, read_session_token
from app.core.settings import Settings
from app.db.client import GraphClient
from app.models.account import Account, SessionClaims
from app.services.account_service import AccountService
from app.services.network_service import NetworkService
from app.services.person_service import PersonService
from app.services.referral_service import ReferralService
from app.services.search_service import SearchService


def get_graph(request: Request) -> GraphClient:
    """Return the process-wide graph client created by the lifespan."""
    # `state` is untyped (`Any` attribute access); the lifespan is what actually
    # guarantees this is a GraphClient, and mypy has no visibility into it.
    return cast(GraphClient, request.app.state.graph)


def get_settings_dep(request: Request) -> Settings:
    """Return the validated settings resolved at startup.

    Reads from app state rather than calling ``get_settings()`` again so that a
    test overriding settings changes them everywhere, not just at boot.
    """
    # Same as `get_graph` above: the lifespan guarantees the type, not the type
    # checker.
    return cast(Settings, request.app.state.settings)


#: Handler-signature aliases.
GraphDep = Annotated[GraphClient, Depends(get_graph)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]


def get_account_service(graph: GraphDep) -> AccountService:
    """Build a service per request. Services are stateless and cheap; the pooled
    resource is the client they wrap, not the service itself."""
    return AccountService(graph)


AccountServiceDep = Annotated[AccountService, Depends(get_account_service)]


async def get_session_claims(request: Request, settings: SettingsDep) -> SessionClaims | None:
    """Decode the session cookie, or None if there isn't one or it doesn't
    verify.

    Split out from ``get_current_account`` so the token is decoded exactly
    once per request and shared by every dependency that needs something out
    of it -- Veloce caches a dependency's result for the lifetime of the
    request, so ``get_current_account`` and ``get_current_account_name`` both
    depending on this costs one decode, not two. Returns None for every
    untrustworthy token rather than raising, so a stale or tampered cookie
    renders a signed-out page instead of an error.
    """
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None
    return read_session_token(token, settings.jwt_secret.get_secret_value())


CurrentSessionClaims = Annotated[SessionClaims | None, Depends(get_session_claims)]


async def get_current_account(
    claims: CurrentSessionClaims, accounts: AccountServiceDep
) -> Account | None:
    """Resolve the signed-in account, or None.

    The account is re-read from the graph rather than trusted from the
    token's claims: a token whose account was deleted must not keep working.
    That's the one property in this whole dependency chain that has to stay
    a database round trip on every request, no matter what else here becomes
    cheaper -- see ``get_current_account_name`` below for the one thing that
    deliberately does *not* re-read from the graph, and why that's safe.
    Public pages depend on this; only write routes depend on
    ``require_account``.
    """
    if claims is None:
        return None
    return await accounts.get_by_id(claims.account_id)


# Defined immediately after its provider, and before anything annotates with
# it. `from __future__ import annotations` would make a forward reference work
# by accident, but a reader should not have to know that to follow the file.
CurrentAccount = Annotated[Account | None, Depends(get_current_account)]


async def require_account(account: CurrentAccount) -> Account:
    """Demand an authenticated account. Used by every write route.

    Raises veloce's own ``HTTPException`` rather than a ``VouchError``
    subclass: ``app.api.errors`` registers a dedicated ``HTTPException``
    handler precisely so framework-native exceptions like this one keep
    veloce's own correct rendering instead of being shadowed by the app's
    broader ``Exception`` catch-all -- see that module's docstring. (This was
    briefly not the case; ``tests/api/test_auth.py`` exercises this through a
    real request rather than trusting that the raise "just works".)
    """
    if account is None:
        raise HTTPException(status_code=401, detail="Sign in to do that.")
    return account


RequiredAccount = Annotated[Account, Depends(require_account)]


async def get_viewer_id(account: CurrentAccount, settings: SettingsDep) -> str:
    """Whose perspective the graph is being viewed from.

    Falls back to the demo protagonist when signed out, which is what keeps
    every read route usable without an account.
    """
    return account.person_id if account else settings.default_person_id


ViewerId = Annotated[str, Depends(get_viewer_id)]


def get_person_service(graph: GraphDep) -> PersonService:
    return PersonService(graph)


PersonServiceDep = Annotated[PersonService, Depends(get_person_service)]


async def get_current_account_name(
    account: CurrentAccount, claims: CurrentSessionClaims, people: PersonServiceDep
) -> str | None:
    """The signed-in account holder's display name, or None when signed out.

    A person's name, not their account's email address, is what the header
    should show once signed in -- an email is a login credential, not
    something a user wants to see about themselves in navigation. Account
    and Person are deliberately separate models (see app.models.account's
    own module docstring: most people in the graph never have an account),
    so the name doesn't live on Account itself.

    Reads the name from the session token's claims first -- zero database
    calls, since the token was already decoded (and its signature verified)
    to resolve ``account`` above. Falls back to
    ``PersonService.get_display_name`` (one property, no ``OPTIONAL MATCH``,
    no ``collect()`` -- see that method's own docstring) only for a token
    minted before this field existed, or by a path not yet updated to supply
    it, so a session in that window still gets a header instead of a blank
    one.

    Still gated on ``account``, not just on the claims: a token can be
    validly signed and unexpired while the account it names no longer
    exists (deleted after the token was issued), and ``account`` is the
    thing that catches that -- ``get_current_account`` re-reads it from the
    graph on every request specifically so revocation takes effect
    immediately. Reading a name straight off ``claims`` without that gate
    would show a name for a signed-out visitor whenever their stale token
    happened to carry one. ``name`` itself is fine to trust from the token
    unverified against the graph, because it is decorative, not an
    authorisation claim -- see ``SessionClaims``' own docstring for why that
    distinction has to hold.

    Measured: this used to call ``get_profile``, the structurally heaviest
    query in the app (five chained ``OPTIONAL MATCH``es), to read one field
    off the result -- a hygiene problem regardless of wall clock, since
    ``PERSON_PROFILE_CYPHER`` happens to already sit at the network floor on
    today's 500-person instance. The version here is what actually removes
    a database round trip: once the token carries a name (i.e. for every
    session minted after this change), the count for a signed-in page drops
    by exactly one call -- confirmed for ``/`` and ``/people/{id}`` in the
    project's build notes.
    """
    if account is None:
        return None
    if claims is not None and claims.name is not None:
        return claims.name
    return await people.get_display_name(account.person_id)


CurrentAccountName = Annotated[str | None, Depends(get_current_account_name)]


def get_search_service(graph: GraphDep) -> SearchService:
    return SearchService(graph)


SearchServiceDep = Annotated[SearchService, Depends(get_search_service)]


def get_referral_service(graph: GraphDep) -> ReferralService:
    return ReferralService(graph)


ReferralServiceDep = Annotated[ReferralService, Depends(get_referral_service)]


def get_network_service(graph: GraphDep) -> NetworkService:
    return NetworkService(graph)


NetworkServiceDep = Annotated[NetworkService, Depends(get_network_service)]
