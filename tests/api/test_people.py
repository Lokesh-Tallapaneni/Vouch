from __future__ import annotations

from veloce import TestClient

from app.api.dependencies import get_graph
from app.core.security import SESSION_COOKIE_NAME, issue_session_token
from app.main import create_app
from app.models.account import SessionClaims
from tests.conftest import DUMMY_SETTINGS_ENV
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

ACCOUNT_ROW = {
    "id": "acc-1",
    "email": "a@b.com",
    "person_id": "p0001",
    "created_at": "2026-08-16T10:00:00Z",
}


def _client(graph: FakeGraph) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_graph] = lambda: graph
    return TestClient(app)


def _csrf_headers(client: TestClient) -> dict[str, str]:
    """Mint and echo a CSRF token so a PATCH clears CSRFMiddleware's
    double-submit check and reaches the route under test -- see
    tests/api/test_security_headers.py for the middleware's own coverage."""
    client.get("/health")  # a safe-method request mints the csrf_token cookie
    return {"x-csrf-token": client.cookies["csrf_token"]}


def test_a_profile_is_readable_without_signing_in() -> None:
    # The demo must work with no account. This is the test that protects that.
    with _client(FakeGraph({"OPTIONAL MATCH": [PROFILE_ROW]})) as client:
        response = client.get("/api/v1/people/p0001")
    assert response.status_code == 200
    assert response.json()["name"] == "Priya Sharma"


def test_an_unknown_person_returns_404() -> None:
    with _client(FakeGraph({})) as client:
        assert client.get("/api/v1/people/ghost").status_code == 404


def test_updating_a_profile_without_signing_in_returns_401() -> None:
    with _client(FakeGraph({})) as client:
        headers = _csrf_headers(client)
        response = client.patch("/api/v1/people/me", json={"title": "Principal"}, headers=headers)
    assert response.status_code == 401


def test_a_whitespace_only_patch_field_returns_422_not_500() -> None:
    # Regression: this used to reach a pydantic ValidationError raised inside
    # the handler body -- neither an HTTPException nor a VouchError -- which
    # fell through to the catch-all and rendered as a 500. Rejection has to
    # happen in request parsing, before the handler runs, so it renders as the
    # 422 a bad request actually is.
    graph = FakeGraph({"MATCH (a:Account {id": [ACCOUNT_ROW]})
    with _client(graph) as client:
        headers = _csrf_headers(client)
        token = issue_session_token(
            SessionClaims(account_id="acc-1", person_id="p0001"),
            DUMMY_SETTINGS_ENV["JWT_SECRET"],
        )
        client.cookies.update({SESSION_COOKIE_NAME: token})
        response = client.patch("/api/v1/people/me", json={"title": "   "}, headers=headers)
    assert response.status_code == 422


def test_updating_my_profile_while_signed_in_writes_to_my_own_id() -> None:
    # /people/me takes its target from the session, never from the request --
    # this proves that end-to-end: the write lands on p0001 (the signed-in
    # account's person_id) even though nothing in the request body or path
    # names it.
    graph = FakeGraph(
        {
            "MATCH (a:Account {id": [ACCOUNT_ROW],
            "SET p += $changes": [PROFILE_ROW],
            "OPTIONAL MATCH": [PROFILE_ROW],
        }
    )
    with _client(graph) as client:
        headers = _csrf_headers(client)
        token = issue_session_token(
            SessionClaims(account_id="acc-1", person_id="p0001"),
            DUMMY_SETTINGS_ENV["JWT_SECRET"],
        )
        client.cookies.update({SESSION_COOKIE_NAME: token})
        response = client.patch(
            "/api/v1/people/me", json={"title": "Principal Engineer"}, headers=headers
        )
    assert response.status_code == 200
    assert response.json()["name"] == "Priya Sharma"
    write = next(call for call in graph.calls if call.write)
    assert write.params == {"person_id": "p0001", "changes": {"title": "Principal Engineer"}}
