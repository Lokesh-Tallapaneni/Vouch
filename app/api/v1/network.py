"""Network-health endpoints."""

from __future__ import annotations

from veloce import Router

from app.api.dependencies import NetworkServiceDep
from app.schemas.common import ERROR_RESPONSES
from app.schemas.network import BrokerResponse, BusFactorRiskResponse

router = Router(prefix="/network", tags=["network"])


@router.get(
    "/brokers",
    response_model=list[BrokerResponse],
    summary="Find network brokers",
    response_description="People bridging the most otherwise-disconnected team pairs.",
    responses=ERROR_RESPONSES,
)
async def list_brokers(network: NetworkServiceDep, limit: int = 15) -> list[BrokerResponse]:
    """People who are the only bridge between otherwise-disconnected teams."""
    brokers = await network.find_brokers(limit=limit)
    return [BrokerResponse.model_validate(b, from_attributes=True) for b in brokers]


@router.get(
    "/bus-factor",
    response_model=list[BusFactorRiskResponse],
    summary="Find single-point-of-failure skills",
    response_description="Project/skill pairs held by exactly one contributor.",
    responses=ERROR_RESPONSES,
)
async def list_bus_factor_risks(
    network: NetworkServiceDep, limit: int = 25
) -> list[BusFactorRiskResponse]:
    """Skills on a project held by exactly one person."""
    risks = await network.find_bus_factor_risks(limit=limit)
    return [BusFactorRiskResponse.model_validate(r, from_attributes=True) for r in risks]
