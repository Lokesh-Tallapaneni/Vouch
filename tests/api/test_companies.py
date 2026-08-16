"""API-level tests for app.api.v1.companies: search and insiders.

Both endpoints previously had service-level coverage only -- routing,
dependency wiring, and response serialisation were untested end to end. That
mattered most here: `GET /companies?q=` returns a bare `list[str]`, the least
conventional response shape in the API, and nothing proved it actually
serialises that way through a real request rather than through
`response_model`'s Python-level validation alone.
"""

from __future__ import annotations

from veloce import TestClient

from app.api.dependencies import get_graph
from app.main import create_app
from tests.support.fake_graph import FakeGraph

INSIDER_ROW = {
    "person_id": "p0007",
    "name": "Meera Nair",
    "title": "Engineering Manager",
    "chain": ["Lokesh Tallapaneni", "Priya Sharma", "Meera Nair"],
    "contexts": ["team", "project"],
    "strengths": [0.82, 0.55],
    "hops": 2,
    "confidence": 0.45,
}


def _client(graph: FakeGraph) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_graph] = lambda: graph
    return TestClient(app)


def test_companies_search_returns_bare_names_without_signing_in() -> None:
    with _client(FakeGraph({"toLower(c.name) STARTS WITH": [{"name": "Everline"}]})) as client:
        response = client.get("/api/v1/companies?q=ev")
    assert response.status_code == 200
    # Bare list[str], not a list of {"name": ...} objects.
    assert response.json() == ["Everline"]


def test_companies_search_below_the_minimum_length_returns_200_with_an_empty_list() -> None:
    with _client(FakeGraph({"toLower(c.name) STARTS WITH": [{"name": "Everline"}]})) as client:
        response = client.get("/api/v1/companies?q=e")
    assert response.status_code == 200
    assert response.json() == []


def test_company_insiders_are_returned_with_their_route_without_signing_in() -> None:
    with _client(FakeGraph({"*1..4": [INSIDER_ROW]})) as client:
        response = client.get("/api/v1/companies/Everline/insiders")
    assert response.status_code == 200
    body = response.json()
    assert body[0]["name"] == "Meera Nair"
    assert body[0]["route"]["confidence"] == 0.45
    assert body[0]["route"]["hop_details"][0]["from_name"] == "Lokesh Tallapaneni"


def test_a_company_with_no_reachable_insiders_returns_200_with_an_empty_list() -> None:
    # "Nobody reachable within the hop ceiling" is a legitimate answer, not
    # an error -- the UI renders this as an empty state.
    with _client(FakeGraph({})) as client:
        response = client.get("/api/v1/companies/Nowhere-Inc/insiders")
    assert response.status_code == 200
    assert response.json() == []
