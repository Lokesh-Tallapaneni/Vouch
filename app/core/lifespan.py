"""Application lifespan.

Owns the only resource in this application with a lifetime: the CognoDB client
and its connection pool. Created once before ``yield``, closed once after --
that ``yield`` is the seam where the pool's lifetime is defined.

Two failure modes, deliberately handled differently:

* **Bad configuration is fatal.** ``get_settings()`` raises before the server
  binds. There is no useful degraded mode for "we don't know where the database
  is", and failing at boot names the offending variable.
* **An unreachable graph is not.** The app boots, ``/ready`` reports the
  problem, and pages render their error state. A process that refuses to start
  because a dependency is down turns a recoverable outage into a crash loop --
  and it is exactly the behaviour the assignment probes with "graceful error
  handling when the database is unreachable".

``VOUCH_SKIP_STARTUP_PROBE`` exists for one narrow reason: a unit test that
boots the app through ``TestClient(create_app())`` gets routes wired to a fake
graph via ``app.dependency_overrides``, but the lifespan itself still builds a
real ``GraphClient`` and would otherwise pay a real network round trip on
every single test. This flag skips *only* that round trip so unit suites stay
socket-free. It is not a second, more lenient path for a genuinely unreachable
database -- that path already exists above, is already tolerant, and is
exactly what Task 20's integration tests exercise for real.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from veloce import Veloce

from app.core.logging import configure_logging, get_logger
from app.core.settings import get_settings
from app.db.client import GraphClient

log = get_logger("lifespan")


@asynccontextmanager
async def lifespan(app: Veloce) -> AsyncGenerator[None]:
    """Start and stop process-wide resources."""
    settings = get_settings()
    configure_logging(settings)

    graph = GraphClient.connect(settings)
    app.state.settings = settings
    app.state.graph = graph

    if os.environ.get("VOUCH_SKIP_STARTUP_PROBE") == "1":
        log.info("VOUCH_SKIP_STARTUP_PROBE=1 -- skipping the startup connectivity probe")
    else:
        is_ready, detail = await graph.check()
        if is_ready:
            log.info("connected to graph at %s", settings.cognodb_uri)
        else:
            log.warning("starting with an unreachable graph; /ready will report it: %s", detail)

    try:
        yield
    finally:
        await graph.aclose()
        log.info("graph client closed, connection pool drained")
