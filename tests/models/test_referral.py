from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.referral import IntroductionRoute, RouteHop


def test_route_hop_rejects_a_strength_above_one() -> None:
    with pytest.raises(ValidationError):
        RouteHop(from_name="A", to_name="B", context="colleagues", strength=1.5)


def test_introduction_route_rejects_a_negative_confidence() -> None:
    with pytest.raises(ValidationError):
        IntroductionRoute(chain=["A", "B"], hops=1, confidence=-0.1)


def test_introduction_route_defaults_hop_details_to_empty() -> None:
    route = IntroductionRoute(chain=["A", "B"], hops=1, confidence=0.5)
    assert route.hop_details == []
