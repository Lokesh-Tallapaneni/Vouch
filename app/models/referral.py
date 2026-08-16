"""Introduction-route view models.

The route *is* the answer this application exists to give, so it gets a
first-class type rather than being passed around as a list of strings.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RouteHop(BaseModel):
    """One link in a chain, with the reason those two people know each other."""

    from_name: str
    to_name: str
    context: str
    strength: float = Field(ge=0.0, le=1.0)


class IntroductionRoute(BaseModel):
    """A ranked path from the viewer to a target.

    ``confidence`` is tie strength multiplied along the whole chain, so a
    three-hop route through close colleagues can outrank a two-hop route
    through near-strangers. Hop counting alone is what makes a people-graph
    demo boring.
    """

    chain: list[str]
    hops: int
    confidence: float = Field(ge=0.0, le=1.0)
    hop_details: list[RouteHop] = Field(default_factory=list)


class CompanyInsider(BaseModel):
    """Someone currently at the target company, plus the best route to them."""

    person_id: str
    name: str
    title: str
    route: IntroductionRoute
