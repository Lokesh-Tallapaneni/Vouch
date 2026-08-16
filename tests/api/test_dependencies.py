"""Tests for the shared request dependencies that aren't already exercised
end to end through a route (auth/person dependencies mostly are -- see
tests/api/test_auth.py, tests/api/test_people.py).

``get_current_account_name`` gets its own coverage here rather than only
through a page route: it's a plain async function, cheap to call directly,
and the thing worth pinning is a call-count contract (how many database
round trips it costs), which is easiest to see with nothing else in the way.
"""

from __future__ import annotations

from app.api.dependencies import get_current_account_name
from app.models.account import Account
from app.services.person_service import PersonService
from tests.support.fake_graph import FakeGraph

_ACCOUNT = Account(
    id="acc-1", email="a@b.com", person_id="p0001", created_at="2026-08-16T10:00:00Z"
)


async def test_signed_out_costs_no_database_call() -> None:
    graph = FakeGraph({"RETURN p.name AS name": [{"name": "Priya Sharma"}]})
    name = await get_current_account_name(None, PersonService(graph))
    assert name is None
    assert graph.calls == []


async def test_signed_in_resolves_the_name_with_a_single_cheap_call() -> None:
    # Hygiene fix, not a measured latency win on today's small dataset (see
    # get_current_account_name's own docstring for the honest numbers): this
    # used to call PersonService.get_profile -- the structurally heaviest
    # query in the app, five OPTIONAL MATCHes and four collect()s -- to read
    # one field off the result. Still one call either way; what's pinned
    # here is that it's no longer shaped like the profile query.
    graph = FakeGraph({"RETURN p.name AS name": [{"name": "Priya Sharma"}]})
    name = await get_current_account_name(_ACCOUNT, PersonService(graph))
    assert name == "Priya Sharma"
    assert len(graph.calls) == 1
    assert "OPTIONAL MATCH" not in graph.calls[0].cypher
    assert "collect(" not in graph.calls[0].cypher
