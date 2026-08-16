"""Introduction-route wire contract."""

from __future__ import annotations

from pydantic import Field

from app.schemas.common import SchemaBase


class RouteHopResponse(SchemaBase):
    from_name: str = Field(description="Person at the start of this hop.")
    to_name: str = Field(description="Person at the end of this hop.")
    context: str = Field(
        description="Why these two know each other.",
        examples=["team", "project", "former-colleague"],
    )
    strength: float = Field(ge=0.0, le=1.0, description="Tie strength, 0 to 1.", examples=[0.82])


class IntroductionRouteResponse(SchemaBase):
    chain: list[str] = Field(
        description="Names from the viewer to the target, in order.",
        examples=[["Lokesh Tallapaneni", "Priya Sharma", "Arjun Rao"]],
    )
    hops: int = Field(description="Number of introductions required.", examples=[2])
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Tie strength multiplied along the chain. Higher is likelier to work.",
        examples=[0.45],
    )
    hop_details: list[RouteHopResponse] = Field(
        default_factory=list, description="Per-hop breakdown of the chain."
    )


class CompanyInsiderResponse(SchemaBase):
    person_id: str = Field(description="Person identifier.", examples=["p0007"])
    name: str = Field(description="Full name.", examples=["Meera Nair"])
    title: str = Field(description="Job title.", examples=["Engineering Manager"])
    route: IntroductionRouteResponse = Field(description="The strongest route to this person.")
