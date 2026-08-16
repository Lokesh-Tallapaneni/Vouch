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


def test_signed_out_pages_explain_whose_network_it_is() -> None:
    # A reviewer landing on any page while signed out is browsing as the
    # demo protagonist -- the header has to say so, or every chain on the
    # site starts from an unexplained stranger. "Demo -- ..." rather than
    # "Viewing as ... the demo account", which used to sit right next to
    # the Sign in / Sign up links and read as contradicting them.
    with _client(FakeGraph({})) as client:
        response = client.get("/")
    assert "Lokesh Tallapaneni" in response.text
    assert "Demo" in response.text


def test_the_demo_accounts_own_profile_explains_itself() -> None:
    protagonist_row = {**PROFILE_ROW, "id": "me", "name": "Lokesh Tallapaneni"}
    with _client(FakeGraph({"OPTIONAL MATCH": [protagonist_row]})) as client:
        response = client.get("/people/me")
    assert "demo account" in response.text


def test_signed_in_pages_show_the_persons_name_not_their_email() -> None:
    account_row = {
        "id": "acc-1",
        "email": "priya@example.com",
        "person_id": "p0001",
        "created_at": "2026-08-16T10:00:00Z",
    }
    graph = FakeGraph(
        {
            # FIND_ACCOUNT_BY_EMAIL_CYPHER (login) and FIND_ACCOUNT_BY_ID_CYPHER
            # (get_current_account, re-resolving the account from the session
            # cookie on every later request) are two different queries -- the
            # follow-up GET below needs the second one registered too, or
            # current_account silently resolves to None and the page renders
            # as if never signed in.
            "MATCH (a:Account {email": [
                {**account_row, "password_hash": hash_account_password(PASSWORD)}
            ],
            "MATCH (a:Account {id": [account_row],
            "OPTIONAL MATCH": [{**PROFILE_ROW, "name": "Priya Sharma"}],
        }
    )
    with _client(graph) as client:
        client.get("/sign-in")
        signed_in = client.post(
            "/sign-in",
            data={
                "email": "priya@example.com",
                "password": PASSWORD,
                "csrf_token": client.cookies["csrf_token"],
            },
            follow_redirects=False,
        )
        response = client.get(signed_in.headers["location"])
    assert "Priya Sharma" in response.text
    assert "priya@example.com" not in response.text
    assert "Signed in as Priya Sharma." in response.text


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
    assert response.headers["location"] == "/sign-in?reason=profile"


def test_the_signin_page_explains_a_redirect_from_profile() -> None:
    with _client(FakeGraph({})) as client:
        response = client.get("/sign-in?reason=profile")
    assert "Sign in to edit your profile." in response.text


def test_the_company_page_names_the_shared_intermediary() -> None:
    # Everline in the real dataset: most routes to its insiders run through
    # the same person -- the insight is meant to say so instead of leaving
    # a reader to notice the repetition themselves.
    rows = [
        {
            "person_id": f"p{i:04d}",
            "name": f"Insider {i}",
            "title": "Engineer",
            "chain": ["Lokesh Tallapaneni", "Ananya Kowalski", f"Insider {i}"],
            "contexts": ["team", "project"],
            "strengths": [0.78, 0.55],
            "hops": 2,
            "confidence": 0.42,
        }
        for i in range(3)
    ]
    graph = FakeGraph(
        {"MATCH (insider:Person)-[:WORKED_AT {current: true}]->(:Company {name: $company})": rows}
    )
    with _client(graph) as client:
        response = client.get("/companies/Everline")
    assert "Ananya Kowalski is your way into Everline." in response.text
    assert "3 of your 3 routes" in response.text


def test_the_company_page_reframes_a_barely_reachable_company() -> None:
    rows = [
        {
            "person_id": "p0999",
            "name": "Distant Person",
            "title": "Engineer",
            "chain": ["Lokesh Tallapaneni", "A", "B", "C", "Distant Person"],
            "contexts": ["team", "project", "former-colleague", "project"],
            "strengths": [0.7, 0.5, 0.3, 0.4],
            "hops": 4,
            "confidence": 0.2,
        }
    ]
    graph = FakeGraph(
        {"MATCH (insider:Person)-[:WORKED_AT {current: true}]->(:Company {name: $company})": rows}
    )
    with _client(graph) as client:
        response = client.get("/companies/CadenceRetail?max_hops=4")
    assert "Your network barely reaches CadenceRetail." in response.text
    assert "4 introductions long" in response.text


def test_the_network_page_renders_a_shell_that_lazy_loads_both_panels() -> None:
    # Brokers takes ~3.9s against the live instance -- a page that blocks on
    # it would render nothing until then. The shell must come back fast and
    # wire each panel to load itself via htmx, not fetch the data inline.
    with _client(FakeGraph({})) as client:
        response = client.get("/network")
    assert response.status_code == 200
    assert 'hx-get="/fragments/brokers"' in response.text
    assert 'hx-get="/fragments/bus-factor-risks"' in response.text
    assert 'hx-trigger="load"' in response.text


def test_the_brokers_fragment_renders_matching_people() -> None:
    graph = FakeGraph(
        {
            "MATCH (a:Person)-[:KNOWS]-(b:Person)-[:KNOWS]-(c:Person)": [
                {
                    "person_id": "p0009",
                    "name": "Arjun Rao",
                    "title": "Tech Lead",
                    "bridged_pairs": 3,
                }
            ]
        }
    )
    with _client(graph) as client:
        response = client.get("/fragments/brokers")
    assert response.status_code == 200
    assert "Arjun Rao" in response.text


def test_the_brokers_fragment_renders_an_empty_state_with_no_data() -> None:
    with _client(FakeGraph({})) as client:
        response = client.get("/fragments/brokers")
    assert response.status_code == 200
    assert "state--empty" in response.text


def test_the_bus_factor_fragment_renders_matching_risks() -> None:
    graph = FakeGraph(
        {
            "MATCH (pr:Project)<-[:WORKS_ON]-(p:Person)-[:HAS_SKILL]->(s:Skill)": [
                {"project": "Atlas", "skill": "Kafka", "sole_holder": "Meera Iyer"}
            ]
        }
    )
    with _client(graph) as client:
        response = client.get("/fragments/bus-factor-risks")
    assert response.status_code == 200
    assert "Meera Iyer" in response.text


def test_the_bus_factor_fragment_renders_an_empty_state_with_no_data() -> None:
    with _client(FakeGraph({})) as client:
        response = client.get("/fragments/bus-factor-risks")
    assert response.status_code == 200
    assert "state--empty" in response.text


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
    # ?signed_in=1 is what lets show_person confirm "routes now start from
    # your network" -- see pages.submit_sign_in.
    assert response.headers["location"] == "/people/p0001?signed_in=1"
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


def test_the_signup_form_does_not_ask_for_a_raw_person_id() -> None:
    # A database primary key like "p0042" is not something a non-technical
    # person can supply -- this is the defect the UX review flagged as
    # failing the assignment's own "usable by a non-technical person"
    # requirement. The claim widget (name search) replaces it.
    with _client(FakeGraph({})) as client:
        response = client.get("/sign-up")
    assert "Find yourself" in response.text
    assert "Start typing your name" in response.text
    assert "p0042" not in response.text
    assert "Your person id" not in response.text
    assert "At least 10 characters" in response.text


def test_the_claim_search_fragment_lets_you_select_a_result() -> None:
    graph = FakeGraph(
        {
            "WHERE toLower(p.name) STARTS WITH": [
                {"id": "p0264", "name": "Lucas Bhat", "title": "Designer"}
            ]
        }
    )
    with _client(graph) as client:
        response = client.get("/fragments/claim-search?q=luc")
    assert response.status_code == 200
    assert 'hx-get="/fragments/claim-select?person_id=p0264"' in response.text
    assert "Lucas Bhat" in response.text


def test_selecting_a_claim_result_populates_the_hidden_field() -> None:
    graph = FakeGraph({"OPTIONAL MATCH": [{**PROFILE_ROW, "id": "p0264", "name": "Lucas Bhat"}]})
    with _client(graph) as client:
        response = client.get("/fragments/claim-select?person_id=p0264")
    assert response.status_code == 200
    assert 'name="person_id" value="p0264"' in response.text
    assert "Claiming" in response.text and "Lucas Bhat" in response.text


def test_signing_up_keeps_the_selection_and_email_after_a_rejected_password() -> None:
    # AccountCreate's own password validator rejects "short" before any
    # query runs, so only the redisplay lookup (get_profile) needs a row.
    graph = FakeGraph({"OPTIONAL MATCH": [{**PROFILE_ROW, "id": "p0264", "name": "Lucas Bhat"}]})
    with _client(graph) as client:
        client.get("/sign-up")
        response = client.post(
            "/sign-up",
            data={
                "person_id": "p0264",
                "email": "lucas@example.com",
                "password": "short",
                "csrf_token": client.cookies["csrf_token"],
            },
        )
    assert response.status_code == 422
    assert 'value="lucas@example.com"' in response.text
    assert "Claiming" in response.text and "Lucas Bhat" in response.text


def test_signing_out_clears_the_cookie_and_sends_an_hx_redirect_header() -> None:
    # The old fix relied on hx-on::after-request, which htmx compiles
    # through new Function() -- blocked by this app's CSP (script-src
    # 'self', no unsafe-eval). HX-Redirect is a plain response header, no
    # script execution involved, so it survives that CSP untouched.
    with _client(FakeGraph({})) as client:
        client.get("/")  # primes csrf_token
        response = client.post("/sign-out", headers=_csrf(client))
    assert response.status_code == 204
    assert response.headers["hx-redirect"] == "/"
    cookie = response.headers["set-cookie"]
    assert SESSION_COOKIE_NAME in cookie and "Max-Age=0" in cookie


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
