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
from app.models.account import Account
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


async def get_current_account(
    request: Request, accounts: AccountServiceDep, settings: SettingsDep
) -> Account | None:
    """Resolve the signed-in account, or None.

    Returns None for every untrustworthy token rather than raising, so a stale
    or tampered cookie renders a signed-out page instead of an error. Public
    pages depend on this; only write routes depend on ``require_account``.

    The account is re-read from the graph rather than trusted from the token:
    a token whose account was deleted must not keep working.
    """
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None
    claims = read_session_token(token, settings.jwt_secret.get_secret_value())
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


def get_search_service(graph: GraphDep) -> SearchService:
    return SearchService(graph)


SearchServiceDep = Annotated[SearchService, Depends(get_search_service)]


def get_referral_service(graph: GraphDep) -> ReferralService:
    return ReferralService(graph)


ReferralServiceDep = Annotated[ReferralService, Depends(get_referral_service)]


def get_network_service(graph: GraphDep) -> NetworkService:
    return NetworkService(graph)


NetworkServiceDep = Annotated[NetworkService, Depends(get_network_service)]
