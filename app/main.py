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

from veloce import LoggingMiddleware, RequestIDMiddleware, Veloce

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

    return app


app = create_app()
