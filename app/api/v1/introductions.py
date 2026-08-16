"""Introduction-route endpoints."""

from __future__ import annotations

from veloce import Router

from app.api.dependencies import ReferralServiceDep, ViewerId
from app.schemas.common import ERROR_RESPONSES
from app.schemas.referral import IntroductionRouteResponse

router = Router(prefix="/introductions", tags=["introductions"])


@router.get(
    "",
    response_model=list[IntroductionRouteResponse],
    summary="Find introduction routes to a person",
    response_description="Routes ranked by confidence, strongest first. Empty if none exists.",
    responses=ERROR_RESPONSES,
)
async def list_introduction_routes(
    target_id: str,
    referrals: ReferralServiceDep,
    viewer_id: ViewerId,
    max_hops: int = 5,
    limit: int = 5,
) -> list[IntroductionRouteResponse]:
    """The strongest introduction chains from the viewer to one person.

    Ranked by confidence rather than length: a three-hop route through
    close colleagues beats a two-hop route through near-strangers.
    """
    routes = await referrals.find_routes(viewer_id, target_id, max_hops=max_hops, limit=limit)
    return [IntroductionRouteResponse.model_validate(r, from_attributes=True) for r in routes]
