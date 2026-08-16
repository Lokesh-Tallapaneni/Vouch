"""Tests for the self-hosted /docs and /redoc pages.

Veloce's built-in Swagger UI / ReDoc pages pull their CSS and JS from
cdnjs.cloudflare.com / unpkg.com and bootstrap Swagger UI with an inline
<script> block -- all three blocked outright by this app's CSP
(script-src 'self', style-src 'self', no unsafe-inline; see app.main).
The page still returned 200 -- the HTML shipped fine -- but the browser
refused every asset it needed to actually draw anything, rendering a blank
white screen. A status-code check could never catch that; these assert on
what the *page itself* references and on the CSP header it actually ships
with, which is the only thing a CSP violation actually touches.

ReDoc needed a second fix beyond vendoring: it injects <style> tags into
<head> at runtime (bundled styled-components), which style-src 'self' blocks
just as thoroughly as an inline <script> -- confirmed live in a browser,
where vendoring the JS alone still left the page crashing before it even
fetched the OpenAPI document. /redoc gets a per-request CSP nonce instead;
see app/api/docs.py for why that's the CSP-standard fix and not a policy
weakening.
"""

from __future__ import annotations

import re

from veloce import TestClient

from app.main import create_app

_EXTERNAL_HOSTS = ("cdnjs.cloudflare.com", "unpkg.com", "fonts.googleapis.com")


def test_docs_serves_only_same_origin_assets() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/docs")
    assert response.status_code == 200
    body = response.text
    for host in _EXTERNAL_HOSTS:
        assert host not in body, f"{host} referenced -- CSP would block it"


def test_docs_has_no_inline_script_content() -> None:
    # A <script src="..."> tag is fine; a <script>...</script> block with a
    # body is exactly what script-src 'self' (no unsafe-inline) blocks. This
    # is the regression that produced the blank page in the first place.
    with TestClient(create_app()) as client:
        body = client.get("/docs").text
    for segment in body.split("<script")[1:]:
        tag, _, rest = segment.partition(">")
        if "src=" in tag:
            continue  # an external-file script tag, not an inline block
        inline_body = rest.split("</script>")[0]
        assert inline_body.strip() == "", "inline script content found on /docs"


def test_redoc_serves_only_same_origin_assets() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/redoc")
    assert response.status_code == 200
    body = response.text
    for host in _EXTERNAL_HOSTS:
        assert host not in body, f"{host} referenced -- CSP would block it"


def test_redoc_has_no_inline_script_or_style_content() -> None:
    with TestClient(create_app()) as client:
        body = client.get("/redoc").text
    for segment in body.split("<script")[1:]:
        tag, _, rest = segment.partition(">")
        if "src=" in tag:
            continue
        assert rest.split("</script>")[0].strip() == "", "inline script content found on /redoc"
    for segment in body.split("<style")[1:]:
        tag, _, rest = segment.partition(">")
        if "href=" in tag:
            continue  # not actually a <style> open tag (shouldn't happen, but be strict)
        assert rest.split("</style>")[0].strip() == "", "inline style content found on /redoc"


def test_redoc_carries_a_fresh_csp_nonce_each_request() -> None:
    # The nonce has to (a) exist, (b) match between the response's own CSP
    # header and the data-nonce attribute redoc-init.js reads (a mismatch
    # would mean ReDoc's injected styles carry the wrong nonce and get
    # blocked exactly like before), and (c) change every request -- a fixed
    # value would just be unsafe-inline with extra steps.
    with TestClient(create_app()) as client:
        first = client.get("/redoc")
        second = client.get("/redoc")

    for response in (first, second):
        csp = response.headers["content-security-policy"]
        header_nonce = re.search(r"'nonce-([^']+)'", csp)
        assert header_nonce, f"no nonce source in style-src: {csp}"
        attr_nonce = re.search(r'data-nonce="([^"]+)"', response.text)
        assert attr_nonce, "no data-nonce attribute in the page body"
        assert header_nonce.group(1) == attr_nonce.group(1)
        assert "'self'" in csp
        assert "unsafe-inline" not in csp

    first_nonce = re.search(r"'nonce-([^']+)'", first.headers["content-security-policy"]).group(1)
    second_nonce = re.search(r"'nonce-([^']+)'", second.headers["content-security-policy"]).group(1)
    assert first_nonce != second_nonce


def test_the_openapi_schema_is_still_served() -> None:
    # openapi_url stays enabled regardless of docs_url/redoc_url -- both
    # /docs and /redoc point at it, and tooling (curl, codegen) that only
    # wants the JSON should be unaffected by any of this.
    with TestClient(create_app()) as client:
        response = client.get("/openapi.json")
    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Vouch"


def test_every_vendored_docs_asset_is_served() -> None:
    with TestClient(create_app()) as client:
        for path in (
            "/static/vendor/swagger-ui.min.css",
            "/static/vendor/swagger-ui-bundle.min.js",
            "/static/vendor/docs-init.js",
            "/static/vendor/redoc.standalone.js",
            "/static/vendor/redoc-init.js",
            "/static/vendor/redoc-reset.css",
        ):
            response = client.get(path)
            assert response.status_code == 200, path


def test_docs_pages_respect_the_sites_content_security_policy() -> None:
    # The site's own default CSP is asserted elsewhere
    # (tests/api/test_security_headers.py); this is the one place that
    # matters whether /docs specifically complies with it, since a page can
    # be technically 'self'-only in its own markup while the *site's*
    # policy still weakened to accommodate it elsewhere.
    with TestClient(create_app()) as client:
        csp = client.get("/docs").headers["content-security-policy"]
    assert "unsafe-inline" not in csp
    for host in _EXTERNAL_HOSTS:
        assert host not in csp
