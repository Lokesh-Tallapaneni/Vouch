"""Tests for the security middleware stack: headers, CSP, CSRF, rate limiting.

Covers what create_app() installs after the request-id/logging pair: baseline
hardening headers on every response, a same-origin-only CSP, CSRF rejection of
an unauthenticated forged write (and acceptance of a same-site one that carries
a matching token), and rate limiting scoped to the sign-in route -- the one
endpoint where unlimited attempts are worth something to an attacker.
"""

from __future__ import annotations

import pytest
from veloce import TestClient

from app.api.dependencies import get_graph
from app.main import create_app
from tests.support.fake_graph import FakeGraph


def test_responses_carry_the_baseline_security_headers() -> None:
    with TestClient(create_app()) as client:
        headers = client.get("/health").headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["referrer-policy"] == "strict-origin-when-cross-origin"


def test_a_content_security_policy_is_present_and_forbids_inline_script() -> None:
    with TestClient(create_app()) as client:
        csp = client.get("/health").headers["content-security-policy"]
    assert "default-src" in csp
    assert "unsafe-inline" not in csp.split("script-src")[-1].split(";")[0]


def test_the_csp_names_no_external_host() -> None:
    # htmx is vendored locally at app/static/js/htmx.min.js rather than
    # pulled from a CDN specifically so this holds -- a CDN entry here would
    # be a trust dependency bought for nothing when the alternative is one
    # file in static/.
    with TestClient(create_app()) as client:
        csp = client.get("/health").headers["content-security-policy"]
    assert "http://" not in csp
    assert "https://" not in csp


def test_a_write_without_a_csrf_token_is_rejected() -> None:
    with TestClient(create_app()) as client:
        response = client.patch("/api/v1/people/me", json={"title": "Principal"})
    assert response.status_code in (401, 403)


def test_a_write_carrying_a_matching_csrf_token_clears_the_csrf_check() -> None:
    # Proves the middleware is a genuine double-submit check, not a blanket
    # block on every write: a request that echoes the cookie CSRFMiddleware
    # issued gets past *it* and fails for the next reason instead (no
    # session -- RequiredAccount's 401), never CSRF's 403.
    with TestClient(create_app()) as client:
        client.get("/health")  # a safe-method request mints the CSRF cookie
        token = client.cookies["csrf_token"]
        response = client.patch(
            "/api/v1/people/me",
            json={"title": "Principal"},
            headers={"x-csrf-token": token},
        )
    assert response.status_code == 401


#: RateLimitMiddleware's bucket key falls back through client IP, then
#: X-Forwarded-For, then a User-Agent hash, only reaching a fresh
#: per-request id when none of those are available (deliberately -- see
#: RateLimitMiddleware._bucket_key -- so one anonymous caller can't drain
#: another's budget). veloce's TestClient never populates a real transport
#: peer, so without a stable header here every request in the loop below
#: would land in its own bucket and the limit would never trip.
_STABLE_CLIENT_HEADERS = {"user-agent": "pytest-security-suite"}


def test_the_sign_in_route_is_rate_limited_after_repeated_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # FakeGraph with no rows registered: every attempt resolves as "no such
    # account" and returns 401 fast, with no socket -- the point of this test
    # is the 21st request getting a 429, not the credential outcome.
    #
    # Freezes time.time() (what RateLimitMiddleware's SlidingWindow strategy
    # keys its 60-second buckets on) for the duration of the loop. Without
    # this the test is genuinely flaky, not just slow: SlidingWindow weights
    # a carried-over previous-window count by how far the *current* window
    # has progressed, so a run whose real wall-clock happens to cross a
    # minute boundary partway through the 21 requests can under-count and
    # never trip 429 -- a failure mode this reproduced directly (about 1 run
    # in 6-12) before the freeze was added.
    monkeypatch.setattr("time.time", lambda: 1_700_000_000.0)
    app = create_app()
    app.dependency_overrides[get_graph] = lambda: FakeGraph()
    with TestClient(app) as client:
        client.get("/health", headers=_STABLE_CLIENT_HEADERS)
        token = client.cookies["csrf_token"]
        statuses = [
            client.post(
                "/api/v1/auth/login",
                json={"email": "nobody@example.com", "password": "wrong"},
                headers={"x-csrf-token": token, **_STABLE_CLIENT_HEADERS},
            ).status_code
            for _ in range(21)
        ]
    assert statuses[:20] == [401] * 20
    assert statuses[20] == 429


def test_a_route_outside_the_override_is_not_bound_by_the_sign_in_limit() -> None:
    # The override is scoped to /api/v1/auth/login specifically; a route with
    # no override shares the generous site-wide default instead, so a burst
    # that would exhaust the sign-in budget doesn't touch unrelated traffic.
    with TestClient(create_app()) as client:
        statuses = [client.get("/health").status_code for _ in range(21)]
    assert all(status == 200 for status in statuses)
