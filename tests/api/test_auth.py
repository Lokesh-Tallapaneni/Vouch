from __future__ import annotations

import pytest
from veloce import Router, TestClient

from app.api.dependencies import RequiredAccount, get_graph
from app.core.security import SESSION_COOKIE_NAME, hash_account_password
from app.main import create_app
from tests.support.fake_graph import FakeGraph

PASSWORD = "correct horse battery"


@pytest.fixture
def client_and_graph() -> tuple[TestClient, FakeGraph]:
    graph = FakeGraph(
        {
            # PERSON_EXISTS_CYPHER's own RETURN clause -- not "MATCH (p:Person",
            # which also appears inside CREATE_ACCOUNT_CYPHER (it MATCHes the
            # same person to attach the new account to) and would make every
            # register() call ambiguous between the two registered fragments.
            "RETURN p.id AS id": [{"id": "me"}],
            "MERGE (a:Account": [
                {
                    "id": "acc-1",
                    "email": "a@b.com",
                    "person_id": "me",
                    "created_at": "2026-08-16T10:00:00Z",
                }
            ],
            "MATCH (a:Account {id": [
                {
                    "id": "acc-1",
                    "email": "a@b.com",
                    "person_id": "me",
                    "created_at": "2026-08-16T10:00:00Z",
                }
            ],
        }
    )
    app = create_app()
    app.dependency_overrides[get_graph] = lambda: graph
    with TestClient(app) as client:
        yield client, graph
    app.dependency_overrides.clear()


def _with_login_row(graph: FakeGraph) -> None:
    graph.rows_by_fragment["MATCH (a:Account {email"] = [
        {
            "id": "acc-1",
            "email": "a@b.com",
            "person_id": "me",
            "created_at": "2026-08-16T10:00:00Z",
            "password_hash": hash_account_password(PASSWORD),
        }
    ]


def test_login_with_valid_credentials_sets_an_httponly_cookie(client_and_graph) -> None:
    client, graph = client_and_graph
    _with_login_row(graph)
    response = client.post("/api/v1/auth/login", json={"email": "a@b.com", "password": PASSWORD})
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert SESSION_COOKIE_NAME in cookie
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie


def test_the_session_cookie_carries_every_flag_the_browser_needs(client_and_graph) -> None:
    # Verify the actual header rather than trusting that set_cookie was called
    # with the right arguments -- that's the difference between "we passed the
    # argument" and "the browser will honour it".
    client, graph = client_and_graph
    _with_login_row(graph)
    response = client.post("/api/v1/auth/login", json={"email": "a@b.com", "password": PASSWORD})
    cookie = response.headers["set-cookie"]
    assert f"{SESSION_COOKIE_NAME}=" in cookie
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "SameSite=Lax" in cookie
    assert "Path=/" in cookie


def test_login_with_a_wrong_password_returns_401_and_sets_no_cookie(client_and_graph) -> None:
    client, graph = client_and_graph
    _with_login_row(graph)
    response = client.post("/api/v1/auth/login", json={"email": "a@b.com", "password": "wrong"})
    assert response.status_code == 401
    assert "set-cookie" not in response.headers


def test_login_with_an_unknown_email_returns_the_identical_response_as_a_wrong_password(
    client_and_graph,
) -> None:
    # authenticate() already guarantees this at the service layer; this proves
    # the HTTP layer doesn't reintroduce an account-enumeration oracle with a
    # different status code or message for the two cases.
    client, graph = client_and_graph
    _with_login_row(graph)
    wrong_password = client.post(
        "/api/v1/auth/login", json={"email": "a@b.com", "password": "wrong"}
    )
    unknown_email = client.post(
        "/api/v1/auth/login", json={"email": "nobody@b.com", "password": "whatever"}
    )
    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()


def test_login_response_never_contains_the_password_hash(client_and_graph) -> None:
    client, graph = client_and_graph
    _with_login_row(graph)
    body = client.post("/api/v1/auth/login", json={"email": "a@b.com", "password": PASSWORD}).text
    assert "password_hash" not in body and "$" not in body


def test_session_without_a_cookie_returns_401(client_and_graph) -> None:
    client, _ = client_and_graph
    assert client.get("/api/v1/auth/session").status_code == 401


def test_a_garbage_cookie_is_treated_as_signed_out_not_an_error(client_and_graph) -> None:
    client, _ = client_and_graph
    client.cookies.update({SESSION_COOKIE_NAME: "not-a-real-token"})
    assert client.get("/api/v1/auth/session").status_code == 401


def test_logout_clears_the_cookie(client_and_graph) -> None:
    client, _ = client_and_graph
    response = client.post("/api/v1/auth/logout")
    assert response.status_code == 204
    assert SESSION_COOKIE_NAME in response.headers.get("set-cookie", "")


def test_logout_clears_the_cookie_with_the_same_flags_it_was_set_with(client_and_graph) -> None:
    # veloce's own delete_cookie docstring: a browser only treats the deletion
    # as a replacement for the original cookie if Path/Domain/Secure/SameSite
    # match. Clearing with mismatched flags would leave the original,
    # authenticated Secure+HttpOnly cookie alive in the browser -- so this
    # proves the deletion can actually take effect, not just that a
    # Set-Cookie header with the right name was sent.
    client, _ = client_and_graph
    response = client.post("/api/v1/auth/logout")
    cookie = response.headers["set-cookie"]
    assert f"{SESSION_COOKIE_NAME}=" in cookie
    assert "Max-Age=0" in cookie
    assert "Secure" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie
    assert "Path=/" in cookie


def test_register_rejects_a_weak_password(client_and_graph) -> None:
    client, _ = client_and_graph
    response = client.post(
        "/api/v1/auth/register", json={"email": "a@b.com", "password": "short", "person_id": "me"}
    )
    assert response.status_code == 422


def test_register_creates_an_account_and_signs_it_in(client_and_graph) -> None:
    client, _ = client_and_graph
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "a@b.com", "password": PASSWORD, "person_id": "me"},
    )
    assert response.status_code == 201
    assert response.json()["email"] == "a@b.com"
    assert "password_hash" not in response.text
    cookie = response.headers["set-cookie"]
    assert SESSION_COOKIE_NAME in cookie and "HttpOnly" in cookie


def test_require_account_rejects_an_unauthenticated_write() -> None:
    """`require_account` is what AUTH_RESPONSES' 401 entry documents. No
    business write route exists in this task's scope yet (companies and
    introductions land in later tasks), so this mounts a throwaway route
    depending on `RequiredAccount` directly, to prove the dependency chain
    genuinely reaches the client as a real HTTP 401 -- rather than a 403, a
    redirect, or a 500. It caught exactly that while this test was being
    written: `app.api.errors`'s catch-all `Exception` handler was, at that
    point, shadowing veloce's own default rendering of `HTTPException` (its
    MRO includes `Exception`), turning this into an opaque 500. Fixed at the
    source in `app.api.errors` (a dedicated `HTTPException` handler,
    registered ahead of the catch-all) rather than by working around it here,
    since the same shadowing would otherwise hit every future write route's
    validation errors too, not just this one.
    """
    probe_router = Router(prefix="/test-only")

    @probe_router.post("/write", include_in_schema=False)
    async def _protected_write(account: RequiredAccount) -> dict[str, bool]:
        return {"ok": True}

    app = create_app()
    app.include_router(probe_router)
    with TestClient(app) as client:
        response = client.post("/test-only/write")
    assert response.status_code == 401
    assert response.json() == {"detail": "Sign in to do that."}
