from __future__ import annotations

from app.services.network_service import NetworkService
from tests.support.fake_graph import FakeGraph

#: The brief's own draft test keyed rows on the literal fragment
#: "NOT (a)-[:KNOWS]-(c)" -- stale from before Q3 was rewritten to the
#: pattern comprehension (see app.db.cypher.network's module docstring: a
#: negated pattern predicate doesn't filter on this engine at all). That
#: fragment is not a substring of the corrected query, so it would never
#: match and every "brokers" test below would silently see zero rows. This
#: fragment is unique to BROKERS_CYPHER and is asserted against directly,
#: not just matched on, so a future edit that reintroduces the broken form
#: fails loudly here instead of at 0 rows on a query no one is looking at.
_BROKERS_FRAGMENT = "size([(a)-[:KNOWS]-(c) | 1]) = 0"


async def test_brokers_are_mapped_and_ordered_by_the_query() -> None:
    graph = FakeGraph(
        {
            _BROKERS_FRAGMENT: [
                {"person_id": "p1", "name": "Meera Nair", "title": "EM", "bridged_pairs": 7},
            ]
        }
    )
    brokers = await NetworkService(graph).find_brokers()
    assert brokers[0].bridged_pairs == 7 and brokers[0].name == "Meera Nair"
    # Not a stale-fragment false positive: this is genuinely the query that ran.
    assert _BROKERS_FRAGMENT in graph.calls[0].cypher


async def test_bus_factor_risks_are_mapped() -> None:
    graph = FakeGraph(
        {
            "size(holders) = 1": [
                {"project": "Atlas", "skill": "Cypher", "sole_holder": "Priya Sharma"},
            ]
        }
    )
    risks = await NetworkService(graph).find_bus_factor_risks()
    assert risks[0].project == "Atlas" and risks[0].sole_holder == "Priya Sharma"
    assert "size(holders) = 1" in graph.calls[0].cypher


async def test_an_empty_result_is_an_empty_list() -> None:
    assert await NetworkService(FakeGraph({})).find_brokers() == []


async def test_limits_are_parameters_and_clamped() -> None:
    graph = FakeGraph({_BROKERS_FRAGMENT: []})
    await NetworkService(graph).find_brokers(limit=10_000)
    assert graph.calls[0].params["limit"] <= 100
