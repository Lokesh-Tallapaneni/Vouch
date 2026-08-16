"""Shared request dependencies.

Routes depend on these rather than reaching into ``request.app.state``
themselves. That indirection is what lets a test swap the graph for a fake with
``app.dependency_overrides[get_graph] = fake_graph`` and never open a socket.

Each dependency is also exported as an ``Annotated`` alias, so handler
signatures read as types rather than as plumbing::

    async def get_person(person_id: str, graph: GraphDep) -> PersonProfile: ...
"""

from __future__ import annotations

from typing import Annotated

from veloce import Depends, Request

from app.core.settings import Settings
from app.db.client import GraphClient


def get_graph(request: Request) -> GraphClient:
    """Return the process-wide graph client created by the lifespan."""
    return request.app.state.graph


def get_settings_dep(request: Request) -> Settings:
    """Return the validated settings resolved at startup.

    Reads from app state rather than calling ``get_settings()`` again so that a
    test overriding settings changes them everywhere, not just at boot.
    """
    return request.app.state.settings


#: Handler-signature aliases.
GraphDep = Annotated[GraphClient, Depends(get_graph)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
