from __future__ import annotations

import pytest

from app.core.exceptions import InvalidInputError
from app.services.referral_service import ReferralService
from tests.support.fake_graph import FakeGraph

ROUTE_ROW = {
    "chain": ["Lokesh Tallapaneni", "Priya Sharma", "Arjun Rao"],
    "contexts": ["team", "project"],
    "strengths": [0.82, 0.55],
    "hops": 2,
    "confidence": 0.45,
}

INSIDER_ROW = {
    "person_id": "p0007",
    "name": "Meera Nair",
    "title": "Engineering Manager",
    **ROUTE_ROW,
}


async def test_routes_are_mapped_with_per_hop_detail() -> None:
    routes = await ReferralService(FakeGraph({"allShortestPaths": [ROUTE_ROW]})).find_routes(
        "me", "p0007"
    )
    assert routes[0].hops == 2
    assert routes[0].hop_details[0].from_name == "Lokesh Tallapaneni"
    assert routes[0].hop_details[0].context == "team"
    assert routes[0].hop_details[1].to_name == "Arjun Rao"


async def test_no_path_yields_an_empty_list_not_an_error() -> None:
    # "No route within 5 hops" is a legitimate answer and renders an empty state.
    assert await ReferralService(FakeGraph({})).find_routes("me", "p9999") == []


async def test_hop_count_above_the_ceiling_is_rejected() -> None:
    with pytest.raises(InvalidInputError):
        await ReferralService(FakeGraph({})).find_routes("me", "p1", max_hops=50)


async def test_hop_count_below_one_is_rejected() -> None:
    with pytest.raises(InvalidInputError):
        await ReferralService(FakeGraph({})).find_routes("me", "p1", max_hops=0)


async def test_routing_to_yourself_is_rejected() -> None:
    with pytest.raises(InvalidInputError):
        await ReferralService(FakeGraph({})).find_routes("me", "me")


async def test_the_hop_bound_is_sent_as_a_parameter_not_interpolated() -> None:
    graph = FakeGraph({"allShortestPaths": [ROUTE_ROW]})
    await ReferralService(graph).find_routes("me", "p0007", max_hops=3)
    call = graph.calls[0]
    assert call.params["max_hops"] == 3
    assert "*1..5" in call.cypher, "the literal ceiling must stay in the statement"


#: Unique to COMPANY_INSIDERS_CYPHER: INTRODUCTION_ROUTES_CYPHER's literal
#: ceiling is *1..5, so this also doubles as the assertion (mirroring
#: test_the_hop_bound_is_sent_as_a_parameter_not_interpolated above) that the
#: tighter, query-specific ceiling actually survived in the statement.
_INSIDERS_FRAGMENT = "*1..4"


async def test_company_insiders_carry_their_best_route() -> None:
    graph = FakeGraph({_INSIDERS_FRAGMENT: [INSIDER_ROW]})
    insiders = await ReferralService(graph).find_company_insiders("me", "Everline")
    assert insiders[0].name == "Meera Nair"
    assert insiders[0].route.confidence == 0.45


async def test_company_insiders_hop_count_above_the_ceiling_is_rejected() -> None:
    # Q2's own ceiling (MAX_INSIDER_HOPS) is tighter than Q1's -- this is the
    # untested half of that split: nothing previously proved
    # find_company_insiders enforces its own bound rather than reusing Q1's.
    with pytest.raises(InvalidInputError):
        await ReferralService(FakeGraph({})).find_company_insiders("me", "Everline", max_hops=50)


async def test_company_insiders_hop_count_below_one_is_rejected() -> None:
    with pytest.raises(InvalidInputError):
        await ReferralService(FakeGraph({})).find_company_insiders("me", "Everline", max_hops=0)


async def test_the_insider_hop_bound_is_sent_as_a_parameter_not_interpolated() -> None:
    graph = FakeGraph({_INSIDERS_FRAGMENT: [INSIDER_ROW]})
    await ReferralService(graph).find_company_insiders("me", "Everline", max_hops=2)
    call = graph.calls[0]
    assert call.params["max_hops"] == 2
    assert "*1..4" in call.cypher, "the query-specific literal ceiling must stay in the statement"


async def test_the_route_limit_is_clamped_to_a_sane_maximum() -> None:
    graph = FakeGraph({"allShortestPaths": [ROUTE_ROW]})
    await ReferralService(graph).find_routes("me", "p0007", limit=10_000)
    assert graph.calls[0].params["limit"] <= 50


async def test_the_insider_limit_is_also_clamped_to_a_sane_maximum() -> None:
    graph = FakeGraph({_INSIDERS_FRAGMENT: [INSIDER_ROW]})
    await ReferralService(graph).find_company_insiders("me", "Everline", limit=10_000)
    assert graph.calls[0].params["limit"] <= 50
