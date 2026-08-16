from __future__ import annotations

from veloce import TestClient

from app.api.dependencies import get_graph
from app.core.security import SESSION_COOKIE_NAME, hash_account_password
from app.main import create_app
from tests.support.fake_graph import FakeGraph

PROFILE_ROW = {
    "id": "p0001",
    "name": "Priya Sharma",
    "title": "Staff Engineer",
    "seniority": "staff",
    "headline": "",
    "employment": [],
    "skills": [],
    "projects": [],
    "team": None,
    "mutual_connections": [],
}

PASSWORD = "correct horse battery"


def _client(graph: FakeGraph) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_graph] = lambda: graph
    return TestClient(app)


def _csrf(client: TestClient) -> dict[str, str]:
    """Echo the CSRF cookie CSRFMiddleware minted on a prior request.

    Same pattern tests/api/test_auth.py uses: the client must have made at
    least one request first (any safe method mints the cookie) before a
    POST can carry a matching header.
    """
    return {"x-csrf-token": client.cookies["csrf_token"]}


def test_the_landing_page_renders_without_an_account() -> None:
    with _client(FakeGraph({})) as client:
        response = client.get("/")
    assert response.status_code == 200 and "text/html" in response.headers["content-type"]


def test_a_profile_page_renders_the_person_name() -> None:
    with _client(FakeGraph({"OPTIONAL MATCH": [PROFILE_ROW]})) as client:
        response = client.get("/people/p0001")
    assert "Priya Sharma" in response.text


def test_search_with_no_matches_renders_a_visible_empty_state() -> None:
    # An empty dropdown reads as a broken feature. Say "no matches" instead.
    with _client(FakeGraph({})) as client:
        response = client.get("/fragments/search?q=zzz")
    assert response.status_code == 200 and "No matches" in response.text


def test_a_company_with_no_reachable_insiders_renders_an_empty_state() -> None:
    with _client(FakeGraph({})) as client:
        response = client.get("/companies/Everline")
    assert "No route" in response.text


def test_the_profile_edit_page_redirects_when_signed_out() -> None:
    with _client(FakeGraph({})) as client:
        response = client.get("/profile", follow_redirects=False)
    assert response.status_code in (302, 303, 307)


def test_the_network_page_renders_brokers_and_bus_factor_risks() -> None:
    graph = FakeGraph(
        {
            "MATCH (a:Person)-[:KNOWS]-(b:Person)-[:KNOWS]-(c:Person)": [
                {
                    "person_id": "p0009",
                    "name": "Arjun Rao",
                    "title": "Tech Lead",
                    "bridged_pairs": 3,
                }
            ],
            "MATCH (pr:Project)<-[:WORKS_ON]-(p:Person)-[:HAS_SKILL]->(s:Skill)": [
                {"project": "Atlas", "skill": "Kafka", "sole_holder": "Meera Iyer"}
            ],
        }
    )
    with _client(graph) as client:
        response = client.get("/network")
    assert response.status_code == 200
    assert "Arjun Rao" in response.text
    assert "Meera Iyer" in response.text


def test_the_network_page_renders_empty_states_with_no_data() -> None:
    with _client(FakeGraph({})) as client:
        response = client.get("/network")
    assert response.status_code == 200
    # Two independent empty sections (brokers, bus-factor risks); each must
    # say so rather than rendering a blank list.
    assert response.text.count("state--empty") >= 2


def test_sign_in_page_carries_the_csrf_token_the_form_will_need() -> None:
    with _client(FakeGraph({})) as client:
        client.get("/")  # primes the csrf_token cookie
        response = client.get("/sign-in")
    assert response.status_code == 200
    assert 'name="csrf_token"' in response.text
    # The hidden field's value must be non-empty once a cookie exists, or the
    # very next POST fails the double-submit check before reaching the
    # handler this test means to exercise.
    assert 'value=""' not in response.text.split('name="csrf_token"')[1][:200]


def test_signing_in_with_valid_credentials_redirects_and_sets_a_session_cookie() -> None:
    graph = FakeGraph(
        {
            "MATCH (a:Account {email": [
                {
                    "id": "acc-1",
                    "email": "a@b.com",
                    "person_id": "p0001",
                    "created_at": "2026-08-16T10:00:00Z",
                    "password_hash": hash_account_password(PASSWORD),
                }
            ]
        }
    )
    with _client(graph) as client:
        client.get("/sign-in")  # primes csrf_token
        response = client.post(
            "/sign-in",
            data={
                "email": "a@b.com",
                "password": PASSWORD,
                "csrf_token": client.cookies["csrf_token"],
            },
            follow_redirects=False,
        )
    assert response.status_code == 303
    assert response.headers["location"] == "/people/p0001"
    cookie = response.headers["set-cookie"]
    assert SESSION_COOKIE_NAME in cookie and "HttpOnly" in cookie


def test_signing_in_with_a_wrong_password_rerenders_the_form_with_an_error() -> None:
    graph = FakeGraph(
        {
            "MATCH (a:Account {email": [
                {
                    "id": "acc-1",
                    "email": "a@b.com",
                    "person_id": "p0001",
                    "created_at": "2026-08-16T10:00:00Z",
                    "password_hash": hash_account_password(PASSWORD),
                }
            ]
        }
    )
    with _client(graph) as client:
        client.get("/sign-in")
        response = client.post(
            "/sign-in",
            data={
                "email": "a@b.com",
                "password": "wrong",
                "csrf_token": client.cookies["csrf_token"],
            },
        )
    assert response.status_code == 401
    assert "credentials didn" in response.text  # Jinja escapes the apostrophe to &#39;
    assert "set-cookie" not in response.headers


def test_signing_up_with_an_unknown_person_id_rerenders_with_an_error() -> None:
    # AccountService.register() checks PERSON_EXISTS_CYPHER before writing;
    # an empty FakeGraph means "no such person" -- this proves the web layer
    # surfaces that as an inline form error, not a bare JSON 404.
    with _client(FakeGraph({})) as client:
        client.get("/sign-up")
        response = client.post(
            "/sign-up",
            data={
                "person_id": "p9999",
                "email": "new@b.com",
                "password": PASSWORD,
                "csrf_token": client.cookies["csrf_token"],
            },
        )
    assert response.status_code == 404
    assert "couldn&#39;t find that person" in response.text
    assert "set-cookie" not in response.headers


def test_submitting_the_profile_form_without_a_csrf_token_is_rejected() -> None:
    # CSRFMiddleware sits ahead of every handler on this path -- this proves
    # the profile form is actually inside its protection, not exempted.
    with _client(FakeGraph({})) as client:
        client.get("/")
        response = client.post("/profile", data={"headline": "New headline"})
    assert response.status_code == 403


def test_the_search_fragment_renders_matching_people_as_links() -> None:
    graph = FakeGraph(
        {
            "WHERE toLower(p.name) STARTS WITH": [
                {
                    "id": "p0002",
                    "name": "Arjun Rao",
                    "title": "Tech Lead",
                    "current_company": "Everline",
                }
            ]
        }
    )
    with _client(graph) as client:
        response = client.get("/fragments/search?q=ar")
    assert response.status_code == 200
    assert 'href="/people/p0002"' in response.text
    assert "Arjun Rao" in response.text


def test_the_routes_fragment_renders_a_chain_when_a_route_exists() -> None:
    graph = FakeGraph(
        {
            "allShortestPaths": [
                {
                    "chain": ["Lokesh Tallapaneni", "Priya Sharma"],
                    "contexts": ["team"],
                    "strengths": [0.8],
                    "hops": 1,
                    "confidence": 0.8,
                }
            ]
        }
    )
    with _client(graph) as client:
        response = client.get("/fragments/routes?target_id=p0001")
    assert response.status_code == 200
    assert "Priya Sharma" in response.text
