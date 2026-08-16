"""Liveness and readiness endpoints.

Split on purpose, because they answer different questions and a platform uses
them for different decisions:

* ``/health`` -- *is this process alive?* No database call. If this fails the
  orchestrator should restart the container.
* ``/ready`` -- *can this process serve traffic?* Touches the database. If this
  fails the container is fine and must NOT be restarted; the dependency is
  down. Restarting would only lengthen the outage.

Collapsing the two into one endpoint is the common mistake: a single
database-touching health check means a brief database blip triggers a restart
loop of a perfectly healthy application.
"""

from __future__ import annotations

from veloce import APIRouter, JSONResponse, Request

from app.db.driver import Database

router = APIRouter()


@router.get("/health", include_in_schema=False)
async def health() -> JSONResponse:
    """Liveness. Deliberately does no I/O."""
    return JSONResponse({"status": "ok"})


@router.get("/ready", include_in_schema=False)
async def ready(request: Request) -> JSONResponse:
    """Readiness. Reports the graph connection without ever raising."""
    db: Database = request.app.state.db
    ok, detail = await db.check()
    if ok:
        return JSONResponse({"status": "ready", "db": "ok"})
    return JSONResponse(
        {"status": "degraded", "db": "unreachable", "detail": detail},
        status_code=503,
    )
