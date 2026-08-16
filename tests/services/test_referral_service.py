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


async def test_company_insiders_carry_their_best_route() -> None:
    insiders = await ReferralService(
        FakeGraph({"WORKED_AT {current: true}": [INSIDER_ROW]})
    ).find_company_insiders("me", "Everline")
    assert insiders[0].name == "Meera Nair"
    assert insiders[0].route.confidence == 0.45
