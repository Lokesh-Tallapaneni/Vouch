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
from app.models.account import Account, SessionClaims
from app.services.person_service import PersonService
from tests.support.fake_graph import FakeGraph

_ACCOUNT = Account(
    id="acc-1", email="a@b.com", person_id="p0001", created_at="2026-08-16T10:00:00Z"
)


async def test_signed_out_costs_no_database_call() -> None:
    graph = FakeGraph({"RETURN p.name AS name": [{"name": "Priya Sharma"}]})
    name = await get_current_account_name(None, None, PersonService(graph))
    assert name is None
    assert graph.calls == []


async def test_a_name_carried_in_the_session_token_costs_no_database_call() -> None:
    # The whole point of embedding the name in the token: once it's there,
    # the header is free. Zero calls, not "one cheap call" -- see the
    # sibling test below for the case that still needs a lookup.
    claims = SessionClaims(account_id="acc-1", person_id="p0001", name="Priya Sharma")
    graph = FakeGraph({"RETURN p.name AS name": [{"name": "Someone Else"}]})
    name = await get_current_account_name(_ACCOUNT, claims, PersonService(graph))
    assert name == "Priya Sharma"
    assert graph.calls == []


async def test_a_token_minted_without_a_name_falls_back_to_a_single_cheap_lookup() -> None:
    # Covers a token issued before this field existed, or by a path not yet
    # updated to supply it -- the header must not go blank for that
    # session's remaining lifetime. Still cheap: one property, no
    # OPTIONAL MATCH, no collect() -- not the full profile query.
    claims = SessionClaims(account_id="acc-1", person_id="p0001", name=None)
    graph = FakeGraph({"RETURN p.name AS name": [{"name": "Priya Sharma"}]})
    name = await get_current_account_name(_ACCOUNT, claims, PersonService(graph))
    assert name == "Priya Sharma"
    assert len(graph.calls) == 1
    assert "OPTIONAL MATCH" not in graph.calls[0].cypher
    assert "collect(" not in graph.calls[0].cypher


async def test_a_revoked_account_shows_no_name_even_with_a_name_carrying_token() -> None:
    # The revocation property this dependency must not quietly break: if
    # the account no longer exists, `account` (re-read from the graph, per
    # get_current_account) is None regardless of what a still-valid,
    # still-signed token's claims say. A name must never be shown for a
    # signed-out visitor just because their old token happened to carry one.
    claims = SessionClaims(account_id="acc-1", person_id="p0001", name="Priya Sharma")
    graph = FakeGraph({})
    name = await get_current_account_name(None, claims, PersonService(graph))
    assert name is None
    assert graph.calls == []
