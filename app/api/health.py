"""Liveness and readiness probes.

Deliberately **unversioned**. These are an operational contract with the
platform -- Render, Docker, a load balancer -- not part of the public API, and
that platform's probe URL should never have to change because the application's
API did. Everything under ``/api/v1`` can be superseded by ``/api/v2``;
``/health`` cannot.

The two endpoints answer different questions and drive different decisions:

* ``/health`` -- *is this process alive?* Touches no dependency. If it fails,
  the orchestrator should restart the container.
* ``/ready`` -- *can this process serve traffic?* Touches the graph. If it
  fails, the container is healthy and must **not** be restarted; the dependency
  is down and restarting would only lengthen the outage.

Collapsing them into one dependency-touching health check is the common
mistake: a brief database blip then restart-loops a perfectly good application.
"""

from __future__ import annotations

from veloce import JSONResponse, Router

from app.api.dependencies import GraphDep

router = Router(tags=["system"])


@router.get("/health", include_in_schema=False)
async def check_liveness() -> JSONResponse:
    """Report that the process is alive. Performs no I/O."""
    return JSONResponse({"status": "ok"})


@router.get("/ready", include_in_schema=False)
async def check_readiness(graph: GraphDep) -> JSONResponse:
    """Report whether the graph is reachable. Never raises."""
    is_ready, detail = await graph.check()
    if is_ready:
        return JSONResponse({"status": "ready", "graph": "ok"})
    return JSONResponse(
        {"status": "degraded", "graph": "unreachable", "detail": detail},
        status_code=503,
    )
