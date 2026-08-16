from __future__ import annotations

import pytest
from veloce import Router, TestClient

from app.api.dependencies import RequiredAccount, get_account_service, get_graph
from app.core.security import SESSION_COOKIE_NAME, hash_account_password, read_session_token
from app.main import create_app
from app.models.account import Account, AccountCreate, Credentials
from app.services.account_service import AccountService
from tests.conftest import DUMMY_SETTINGS_ENV
from tests.support.fake_graph import FakeGraph

PASSWORD = "correct horse battery"


def _csrf(client: TestClient) -> dict[str, str]:
    """A header dict carrying the CSRF token CSRFMiddleware already issued.

    Task 17 installed CSRFMiddleware sitewide (double-submit-cookie, see
    app.main), which unsafe-method routes never needed a token for before --
    every write test in this file now needs to echo one, or it never reaches
    the handler it means to exercise. Requires the client to have made at
    least one prior request (any safe method mints the cookie); every caller
    here relies on ``client_and_graph``'s own priming GET for that.
    """
    return {"x-csrf-token": client.cookies["csrf_token"]}


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
        client.get("/health")  # primes the CSRF cookie every write test below echoes
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
    response = client.post(
        "/api/v1/auth/login", json={"email": "a@b.com", "password": PASSWORD}, headers=_csrf(client)
    )
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
    response = client.post(
        "/api/v1/auth/login", json={"email": "a@b.com", "password": PASSWORD}, headers=_csrf(client)
    )
    cookie = response.headers["set-cookie"]
    assert f"{SESSION_COOKIE_NAME}=" in cookie
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "SameSite=Lax" in cookie
    assert "Path=/" in cookie


def test_login_mints_a_token_carrying_the_persons_display_name(client_and_graph) -> None:
    # The whole point of the JWT-embedding fix: the header should read the
    # name straight off the token, with zero extra database calls per
    # signed-in page. Register the name lookup fragment explicitly, keyed
    # to a distinct name from the account fixture's own person, so this
    # can't pass by accident against some other registered row.
    client, graph = client_and_graph
    _with_login_row(graph)
    graph.rows_by_fragment["RETURN p.name AS name"] = [{"name": "Priya Sharma"}]
    response = client.post(
        "/api/v1/auth/login", json={"email": "a@b.com", "password": PASSWORD}, headers=_csrf(client)
    )
    token = response.cookies[SESSION_COOKIE_NAME]
    claims = read_session_token(token, DUMMY_SETTINGS_ENV["JWT_SECRET"])
    assert claims is not None
    assert claims.name == "Priya Sharma"


def test_login_with_a_wrong_password_returns_401_and_sets_no_cookie(client_and_graph) -> None:
    client, graph = client_and_graph
    _with_login_row(graph)
    response = client.post(
        "/api/v1/auth/login", json={"email": "a@b.com", "password": "wrong"}, headers=_csrf(client)
    )
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
        "/api/v1/auth/login", json={"email": "a@b.com", "password": "wrong"}, headers=_csrf(client)
    )
    unknown_email = client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@b.com", "password": "whatever"},
        headers=_csrf(client),
    )
    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()


def test_login_response_never_contains_the_password_hash(client_and_graph) -> None:
    client, graph = client_and_graph
    _with_login_row(graph)
    body = client.post(
        "/api/v1/auth/login", json={"email": "a@b.com", "password": PASSWORD}, headers=_csrf(client)
    ).text
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
    response = client.post("/api/v1/auth/logout", headers=_csrf(client))
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
    response = client.post("/api/v1/auth/logout", headers=_csrf(client))
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
        "/api/v1/auth/register",
        json={"email": "a@b.com", "password": "short", "person_id": "me"},
        headers=_csrf(client),
    )
    assert response.status_code == 422


def test_register_creates_an_account_and_signs_it_in(client_and_graph) -> None:
    client, _ = client_and_graph
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "a@b.com", "password": PASSWORD, "person_id": "me"},
        headers=_csrf(client),
    )
    assert response.status_code == 201
    assert response.json()["email"] == "a@b.com"
    assert "password_hash" not in response.text
    cookie = response.headers["set-cookie"]
    assert SESSION_COOKIE_NAME in cookie and "HttpOnly" in cookie


def test_register_mints_a_token_carrying_the_persons_display_name(client_and_graph) -> None:
    client, graph = client_and_graph
    graph.rows_by_fragment["RETURN p.name AS name"] = [{"name": "Priya Sharma"}]
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "a@b.com", "password": PASSWORD, "person_id": "me"},
        headers=_csrf(client),
    )
    token = response.cookies[SESSION_COOKIE_NAME]
    claims = read_session_token(token, DUMMY_SETTINGS_ENV["JWT_SECRET"])
    assert claims is not None
    assert claims.name == "Priya Sharma"


def test_register_and_login_convert_the_wire_schema_before_calling_the_service() -> None:
    """`register_account`/`log_in` must hand `AccountService` the
    `AccountCreate`/`Credentials` models its methods declare, not the
    `RegisterRequest`/`LoginRequest` schemas the handlers receive off the
    wire. The two pairs are field-for-field identical, so a regression that
    passed the schema straight through would still satisfy every
    response-shape assertion elsewhere in this file -- mypy caught it, not a
    behavioural difference. Only checking the type that actually crosses the
    service boundary catches a reintroduced shortcut here.
    """
    graph = FakeGraph(
        {
            "RETURN p.id AS id": [{"id": "me"}],
            "MERGE (a:Account": [
                {
                    "id": "acc-1",
                    "email": "a@b.com",
                    "person_id": "me",
                    "created_at": "2026-08-16T10:00:00Z",
                }
            ],
        }
    )
    _with_login_row(graph)
    received: dict[str, type] = {}

    class _SpyAccountService(AccountService):
        async def register(self, data: AccountCreate) -> Account:
            received["register"] = type(data)
            return await super().register(data)

        async def authenticate(self, creds: Credentials) -> Account | None:
            received["authenticate"] = type(creds)
            return await super().authenticate(creds)

    app = create_app()
    app.dependency_overrides[get_account_service] = lambda: _SpyAccountService(graph)
    with TestClient(app) as client:
        client.get("/health")  # primes the CSRF cookie both writes below echo
        client.post(
            "/api/v1/auth/register",
            json={"email": "a@b.com", "password": PASSWORD, "person_id": "me"},
            headers=_csrf(client),
        )
        client.post(
            "/api/v1/auth/login",
            json={"email": "a@b.com", "password": PASSWORD},
            headers=_csrf(client),
        )
    app.dependency_overrides.clear()

    assert received["register"] is AccountCreate
    assert received["authenticate"] is Credentials


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
        client.get("/health")  # primes the CSRF cookie -- this test is about
        # RequiredAccount's 401, not CSRF's 403, so it has to clear that check
        # first to reach the dependency it means to exercise.
        response = client.post("/test-only/write", headers=_csrf(client))
    assert response.status_code == 401
    # Field-by-field, not exact-dict equality: the error envelope grew a
    # `reference` (the request id, see app.api.errors) after this test was
    # written, and an exact-dict comparison would go stale every time the
    # envelope grows again rather than just when `detail` itself changes.
    body = response.json()
    assert body["detail"] == "Sign in to do that."
    assert body["reference"] == response.headers["x-request-id"]
