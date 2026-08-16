"""API-level tests for app.api.v1.introductions.

Previously service-level coverage only -- routing, dependency wiring
(ReferralServiceDep, ViewerId), and response serialisation were untested end
to end.
"""

from __future__ import annotations

from veloce import TestClient

from app.api.dependencies import get_graph
from app.main import create_app
from tests.support.fake_graph import FakeGraph

ROUTE_ROW = {
    "chain": ["Lokesh Tallapaneni", "Priya Sharma", "Arjun Rao"],
    "contexts": ["team", "project"],
    "strengths": [0.82, 0.55],
    "hops": 2,
    "confidence": 0.45,
}


def _client(graph: FakeGraph) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_graph] = lambda: graph
    return TestClient(app)


def test_introduction_routes_are_returned_without_signing_in() -> None:
    # Reads stay public -- the demo protagonist (ViewerId's fallback) can be
    # used with no account at all.
    with _client(FakeGraph({"allShortestPaths": [ROUTE_ROW]})) as client:
        response = client.get("/api/v1/introductions?target_id=p0007")
    assert response.status_code == 200
    body = response.json()
    assert body[0]["confidence"] == 0.45
    assert body[0]["hops"] == 2
    assert body[0]["hop_details"][0]["from_name"] == "Lokesh Tallapaneni"


def test_no_route_within_the_hop_ceiling_returns_200_with_an_empty_list() -> None:
    # "No route within N hops" is a legitimate answer, not an error --
    # ReferralService.find_routes returns [] rather than raising, and that
    # has to survive all the way out as a 200, not a 404 or a 500.
    with _client(FakeGraph({})) as client:
        response = client.get("/api/v1/introductions?target_id=p9999")
    assert response.status_code == 200
    assert response.json() == []


def test_a_missing_target_id_is_a_validation_error() -> None:
    # target_id has no default -- omitting it is a malformed request, not an
    # empty result.
    with _client(FakeGraph({})) as client:
        response = client.get("/api/v1/introductions")
    assert response.status_code == 422
