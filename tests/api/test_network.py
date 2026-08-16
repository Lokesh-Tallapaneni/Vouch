"""API-level tests for app.api.v1.network.

Previously service-level coverage only -- routing, dependency wiring, and
response serialisation for both `/network/brokers` and `/network/bus-factor`
were untested end to end. Same gap as tasks 12 and 13, closed on the same
terms: a normal 200, the empty case returning 200 with `[]` rather than an
error, and reads working without authentication.
"""

from __future__ import annotations

from veloce import TestClient

from app.api.dependencies import get_graph
from app.main import create_app
from tests.support.fake_graph import FakeGraph

BROKER_ROW = {"person_id": "p0007", "name": "Meera Nair", "title": "EM", "bridged_pairs": 7}
BUS_FACTOR_ROW = {"project": "Atlas", "skill": "Cypher", "sole_holder": "Priya Sharma"}


def _client(graph: FakeGraph) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_graph] = lambda: graph
    return TestClient(app)


def test_brokers_are_returned_without_signing_in() -> None:
    with _client(FakeGraph({"size([(a)-[:KNOWS]-(c) | 1]) = 0": [BROKER_ROW]})) as client:
        response = client.get("/api/v1/network/brokers")
    assert response.status_code == 200
    body = response.json()
    assert body[0]["name"] == "Meera Nair"
    assert body[0]["bridged_pairs"] == 7


def test_no_brokers_returns_200_with_an_empty_list() -> None:
    with _client(FakeGraph({})) as client:
        response = client.get("/api/v1/network/brokers")
    assert response.status_code == 200
    assert response.json() == []


def test_bus_factor_risks_are_returned_without_signing_in() -> None:
    with _client(FakeGraph({"size(holders) = 1": [BUS_FACTOR_ROW]})) as client:
        response = client.get("/api/v1/network/bus-factor")
    assert response.status_code == 200
    body = response.json()
    assert body[0]["project"] == "Atlas"
    assert body[0]["sole_holder"] == "Priya Sharma"


def test_no_bus_factor_risks_returns_200_with_an_empty_list() -> None:
    with _client(FakeGraph({})) as client:
        response = client.get("/api/v1/network/bus-factor")
    assert response.status_code == 200
    assert response.json() == []
