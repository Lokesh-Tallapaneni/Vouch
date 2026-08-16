"""Tests for the static-file mount create_app() wires up.

A static mount that silently 404s is invisible until someone opens the page
in a browser -- app.main.create_app() already fails fast at wiring time if
app/static/ is missing (mount_static's must_exist check), but that only
proves the directory exists, not that a request for a real file inside it
actually resolves. These hit the mount over HTTP instead.
"""

from __future__ import annotations

from veloce import TestClient

from app.main import create_app


def test_the_vendored_stylesheet_is_served() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/static/css/vouch.css")
    assert response.status_code == 200
    assert "css" in response.headers["content-type"]


def test_the_vendored_htmx_bundle_is_served() -> None:
    # Vendored locally rather than pulled from a CDN -- see the CSP
    # comment in app.main -- so this is the only place it can come from.
    with TestClient(create_app()) as client:
        response = client.get("/static/js/htmx.min.js")
    assert response.status_code == 200
    assert len(response.body) > 0


def test_a_path_outside_the_mounted_directory_does_not_resolve() -> None:
    # Not a security test of StaticFiles' own path-traversal defence (that's
    # veloce's to prove) -- just confirms the mount is scoped to app/static/,
    # not the whole app/ tree it lives under.
    with TestClient(create_app()) as client:
        response = client.get("/static/../main.py")
    assert response.status_code in (400, 403, 404)
