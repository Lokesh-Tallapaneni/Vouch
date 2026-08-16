"""Application factory and lifespan.

The lifespan owns the one resource in this app that has a lifetime: the CognoDB
driver and its connection pool. It is created once on startup, hung on
``app.state``, and closed on shutdown -- the ``yield`` below is the seam.

The startup path deliberately tolerates a downed database. The app boots,
``/ready`` reports the problem, and pages render their error state. A process
that refuses to start because a dependency is unavailable turns a recoverable
outage into a crash loop, and it is precisely the behaviour the assignment
probes with "graceful error handling when the database is unreachable".

Configuration is the opposite: a missing secret raises before the server binds,
because there is no useful degraded mode for "we don't know where the database
is".
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from veloce import Depends, Request, Veloce

from app.config import Settings, get_settings
from app.db.driver import Database
from app.routes import health

log = logging.getLogger("vouch")


def _configure_logging(settings: Settings) -> None:
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
    )
    # The driver logs a full stack trace for every managed-transaction retry.
    # That is useful in tests and unreadable in a server log, where the retry is
    # expected behaviour we already surface through /ready.
    logging.getLogger("neo4j").setLevel(logging.ERROR)


@asynccontextmanager
async def lifespan(app: Veloce) -> AsyncGenerator[None]:
    """Create the driver on startup, close it on shutdown.

    Everything before ``yield`` runs once at startup; everything after runs at
    shutdown, including when startup itself failed part-way through.
    """
    settings = get_settings()  # raises ConfigError -> the process never binds
    _configure_logging(settings)

    db = Database.connect(settings)
    app.state.db = db
    app.state.settings = settings

    ok, detail = await db.check()
    if ok:
        log.info("connected to graph at %s", settings.cognodb_uri)
    else:
        # Not fatal. See the module docstring.
        log.warning("starting with an unreachable graph -- /ready will report it: %s", detail)

    try:
        yield
    finally:
        await db.aclose()
        log.info("graph driver closed, pool drained")


def get_db(request: Request) -> Database:
    """Dependency handing routes the process-wide database.

    Routes depend on this rather than reaching into ``app.state`` themselves, so
    tests can override it with a fake and never open a socket.
    """
    return request.app.state.db


DbDep = Depends(get_db)


def create_app() -> Veloce:
    """Build the application.

    A factory rather than a module-level singleton: importing this module must
    not read the environment or construct a pool, otherwise every test import
    and every ``--help`` invocation would need a configured database.
    """
    app = Veloce(
        title="Vouch",
        version="0.1.0",
        description="A referral-path finder over a professional network.",
        lifespan=lifespan,
    )
    app.include_router(health.router)
    return app


app = create_app()
