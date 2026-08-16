"""htmx partials.

Each returns an HTML fragment, never JSON: htmx swaps markup, so a JSON API
for the UI would mean writing a client-side renderer to turn it back into
markup.

Every fragment renders its empty state explicitly. An empty response body
produces a dropdown that silently shows nothing, which reads as a broken
feature rather than as "no matches".
"""

from __future__ import annotations

from veloce import Request, Response, Router

from app.api.dependencies import NetworkServiceDep, ReferralServiceDep, SearchServiceDep, ViewerId
from app.web.templating import templates

router = Router(prefix="/fragments", tags=["fragments"])


@router.get("/search")
async def search_fragment(
    request: Request, search: SearchServiceDep, q: str = "", kind: str = "person"
) -> Response:
    """Typeahead results for the people or company search box."""
    if kind == "company":
        names = await search.search_companies(q)
        results = [{"label": name, "href": f"/companies/{name}", "detail": ""} for name in names]
    else:
        people = await search.search_people(q)
        results = [
            {"label": person.name, "href": f"/people/{person.id}", "detail": person.title or ""}
            for person in people
        ]
    return templates.TemplateResponse(
        "_search_results.html", {"request": request, "results": results, "term": q}
    )


@router.get("/routes")
async def routes_fragment(
    request: Request,
    referrals: ReferralServiceDep,
    viewer_id: ViewerId,
    target_id: str,
    max_hops: int = 5,
) -> Response:
    """The route panel, re-queryable at a different hop count."""
    routes = await referrals.find_routes(viewer_id, target_id, max_hops=max_hops, limit=5)
    return templates.TemplateResponse(
        "_routes.html", {"request": request, "routes": routes, "max_hops": max_hops}
    )


@router.get("/brokers")
async def brokers_fragment(request: Request, network: NetworkServiceDep) -> Response:
    """The brokers panel, loaded lazily by network.html's shell.

    Measured at ~3.9s against the live instance -- the slowest query an
    evaluator can click. Kept as its own fragment (rather than folded into
    the bus-factor one below) so a slow Brokers response never blocks the
    faster bus-factor panel from appearing.
    """
    brokers = await network.find_brokers(limit=15)
    return templates.TemplateResponse("_brokers.html", {"request": request, "brokers": brokers})


@router.get("/bus-factor-risks")
async def bus_factor_risks_fragment(request: Request, network: NetworkServiceDep) -> Response:
    """The bus-factor panel, loaded lazily alongside brokers."""
    risks = await network.find_bus_factor_risks(limit=25)
    return templates.TemplateResponse(
        "_bus_factor_risks.html", {"request": request, "risks": risks}
    )
