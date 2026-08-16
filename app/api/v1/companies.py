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
    summary="Search companies by name prefix",
    response_description="Matching company names, alphabetical.",
    responses=ERROR_RESPONSES,
)
async def list_companies(search: SearchServiceDep, q: str = "", limit: int = 8) -> list[str]:
    """Typeahead over company names."""
    return await search.search_companies(q, limit=limit)


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
