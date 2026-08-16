"""Company endpoints."""

from __future__ import annotations

from veloce import Router

from app.api.dependencies import ReferralServiceDep, SearchServiceDep, ViewerId
from app.schemas.common import ERROR_RESPONSES
from app.schemas.referral import CompanyInsiderResponse

router = Router(prefix="/companies", tags=["companies"])


@router.get(
    "",
    response_model=list[str],
    summary="List companies, or search them by name prefix",
    response_description=(
        "Company names. Alphabetical when searching; busiest first when listing."
    ),
    responses=ERROR_RESPONSES,
)
async def list_companies(search: SearchServiceDep, q: str = "", limit: int = 8) -> list[str]:
    """Companies in the graph, or those whose name starts with ``q``.

    Without ``q`` this returns the companies with the most current employees
    rather than an empty list. A collection endpoint that answers a bare
    ``GET`` with ``[]`` reads as broken -- which is exactly how it looked in
    the API docs -- and "what companies exist here" is a fair question for a
    caller who has not typed anything yet.
    """
    if q.strip():
        return await search.search_companies(q, limit=limit)
    return await search.list_companies(limit=limit)


@router.get(
    "/{company_name}/insiders",
    response_model=list[CompanyInsiderResponse],
    summary="Find who you can reach at a company",
    response_description="Insiders ranked by route confidence, each with the chain to them.",
    responses=ERROR_RESPONSES,
)
async def list_company_insiders(
    company_name: str,
    referrals: ReferralServiceDep,
    viewer_id: ViewerId,
    max_hops: int = 4,
    limit: int = 10,
) -> list[CompanyInsiderResponse]:
    """People currently at this company, ranked by how reachable they are."""
    insiders = await referrals.find_company_insiders(
        viewer_id, company_name, max_hops=max_hops, limit=limit
    )
    return [CompanyInsiderResponse.model_validate(i, from_attributes=True) for i in insiders]
