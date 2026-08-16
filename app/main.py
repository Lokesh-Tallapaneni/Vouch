"""Application factory.

Wiring only. This module composes settings, lifespan and routers into an app
and does nothing else -- no configuration is read at import time and no
connection pool is built, so importing ``app.main`` is always cheap and always
safe. That is why ``create_app()`` is a factory rather than a module-level
singleton: every test import and every ``--help`` would otherwise need a
configured, reachable database.

Route surface:

    /health, /ready      unversioned operational probes (app.api.health)
    /api/v1/...          versioned JSON API           (app.api.v1)
    /                    server-rendered pages        (app.web, to follow)
"""

from __future__ import annotations

from veloce import (
    CSPMiddleware,
    CSRFMiddleware,
    LoggingMiddleware,
    RateLimitMiddleware,
    RequestIDMiddleware,
    SecurityHeadersMiddleware,
    SlidingWindow,
    Veloce,
)

from app.api import health
from app.api.errors import register_exception_handlers
from app.api.v1 import router as v1
from app.core.lifespan import lifespan

APP_TITLE = "Vouch"
APP_VERSION = "0.1.0"
APP_DESCRIPTION = "A referral-path finder over a professional network, backed by CognoDB."


def create_app() -> Veloce:
    """Build and wire the application."""
    app = Veloce(
        title=APP_TITLE,
        version=APP_VERSION,
        description=APP_DESCRIPTION,
        lifespan=lifespan,
    )

    app.include_router(health.router)
    app.include_router(v1.router)
    register_exception_handlers(app)

    # RequestIDMiddleware first, LoggingMiddleware second: veloce's
    # Middleware pipeline runs process_request in registration order (and
    # process_response in reverse), so registering the id-minting middleware
    # first is what makes request.state.request_id exist before anything
    # downstream -- the route handler, app.api.errors's reference field --
    # runs. Confirmed against veloce's own source, not assumed:
    # `_pipeline.py`'s `build_request_middleware` fuses `process_request`
    # bound methods in forward (registration) order, and `app/dispatch.py`'s
    # `_run_request_phase` walks that fused chain in the order given -- no
    # reversal happens until the response phase (`build_response_middleware`
    # reverses it there instead). Note this ordering does NOT change what
    # veloce's own LoggingMiddleware logs: its access-log line (method, path,
    # status, duration) never reads request_id at all, in either order -- the
    # request id only reaches a log line because app.api.errors reads
    # request.state.request_id itself.
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(LoggingMiddleware)

    app.add_middleware(SecurityHeadersMiddleware)
    # htmx is vendored locally at app/static/js/htmx.min.js rather than pulled
    # from a CDN, so no external host needs to appear in the policy -- a CDN
    # entry here would be a trust dependency bought for nothing when the
    # alternative is one file in static/. CSPMiddleware takes a directive
    # mapping via `policy=`, not the `default_src=`/`script_src=` kwargs an
    # earlier draft of this task assumed -- checked with
    # `inspect.signature(CSPMiddleware.__init__)` rather than guessed.
    app.add_middleware(
        CSPMiddleware,
        policy={
            "default-src": "'self'",
            "script-src": "'self'",
            "style-src": "'self'",
            "img-src": ["'self'", "data:"],
        },
    )
    # Protects the write routes. An earlier design doc argued no CSRF was
    # needed because every route was read-only; profile editing
    # (PATCH /api/v1/people/me) removed that premise. Defaults match how the
    # session cookie itself is already set in app.api.v1.auth (Secure,
    # SameSite=Lax) -- httponly stays False here specifically, since the
    # double-submit pattern requires client-side script to read the cookie
    # and echo it back in the X-CSRF-Token header.
    app.add_middleware(CSRFMiddleware)
    # A generous site-wide floor (an abuse/DoS backstop, not a throttle
    # anyone should hit in normal use) plus a tight override on sign-in
    # specifically -- the one endpoint where unlimited attempts are worth
    # something to an attacker (credential stuffing, brute force). An
    # `overrides` key is the *full* route template including the blueprint
    # prefix (RateLimitMiddleware's own docstring), hence
    # `v1.API_V1_PREFIX` rather than the bare "/auth/login" the route
    # decorator itself is written with. `RateLimitMiddleware(limit=20, ...)`
    # -- what an earlier draft of this task called for -- isn't this
    # constructor's signature either: it takes `max_requests`, and neither
    # form scopes to one route on its own, which is why this uses `strategy=`
    # / `overrides=` instead of the bare `max_requests=` shortcut.
    app.add_middleware(
        RateLimitMiddleware,
        strategy=SlidingWindow(limit=300, window=60),
        overrides={f"{v1.API_V1_PREFIX}/auth/login": SlidingWindow(limit=20, window=60)},
    )

    return app


app = create_app()
