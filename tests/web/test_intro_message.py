from __future__ import annotations

from app.models.referral import IntroductionRoute, RouteHop
from app.web.intro_message import build_intro_message


def _route(hops: list[tuple[str, str, str, float]], confidence: float = 0.5) -> IntroductionRoute:
    hop_details = [RouteHop(from_name=a, to_name=b, context=c, strength=s) for a, b, c, s in hops]
    chain = [hop_details[0].from_name] + [h.to_name for h in hop_details]
    return IntroductionRoute(
        chain=chain, hops=len(hop_details), confidence=confidence, hop_details=hop_details
    )


def test_a_single_hop_route_addresses_the_target_directly() -> None:
    # The first hop already *is* the target -- a direct reach-out, not an
    # introduction request, since there's no one in between to ask.
    route = _route([("Lokesh Tallapaneni", "Priya Sharma", "team", 0.8)])
    message = build_intro_message(route, "Priya Sharma", "Staff Engineer", "Everline")
    assert message.startswith("Hi Priya Sharma,")
    assert "already connected" in message
    assert "same team" in message
    assert "Everline" in message


def test_a_two_hop_route_asks_the_first_hop_to_introduce_the_second() -> None:
    route = _route(
        [
            ("Lokesh Tallapaneni", "Ananya Kowalski", "team", 0.78),
            ("Ananya Kowalski", "Lucas Bhat", "project", 0.55),
        ]
    )
    message = build_intro_message(route, "Lucas Bhat", "Designer", "Everline")
    assert message.startswith("Hi Ananya Kowalski,")
    assert "Lucas Bhat" in message
    assert "Everline" in message
    assert "worked together on a project" in message
    assert "introduce us" in message


def test_a_two_hop_route_does_not_name_the_target_twice() -> None:
    # The second hop's destination *is* the target on a two-hop route --
    # naming them twice ("get in front of Lucas Bhat ... you know Lucas
    # Bhat") reads as a mistake, not emphasis.
    route = _route(
        [
            ("Lokesh Tallapaneni", "Ananya Kowalski", "team", 0.78),
            ("Ananya Kowalski", "Lucas Bhat", "project", 0.55),
        ]
    )
    message = build_intro_message(route, "Lucas Bhat", "Designer", "Everline")
    assert message.count("Lucas Bhat") == 1
    assert "know them" in message


def test_a_longer_route_only_names_the_first_and_second_hop() -> None:
    # The ask is always to the *next* stop, not the whole chain -- asking
    # the first hop to introduce someone they don't know isn't a request
    # they can fulfil. hop[2]'s context ("former-colleague") must not leak
    # into a message that's only asking about hop[1] ("project").
    route = _route(
        [
            ("Lokesh Tallapaneni", "Ananya", "team", 0.8),
            ("Ananya", "Bilal", "project", 0.5),
            ("Bilal", "Chen", "former-colleague", 0.3),
        ]
    )
    message = build_intro_message(route, "Chen", "Engineer", "Cadence Retail")
    assert message.startswith("Hi Ananya,")
    assert "Bilal" in message
    assert "worked together on a project" in message
    assert "used to work together" not in message


def test_the_message_works_without_a_title_or_company() -> None:
    route = _route(
        [
            ("Lokesh Tallapaneni", "Ananya", "team", 0.8),
            ("Ananya", "Bilal", "project", 0.5),
        ]
    )
    message = build_intro_message(route, "Bilal")
    assert "Hi Ananya," in message
    assert "Bilal" in message
    assert " at " not in message.split("noticed")[0]


def test_an_empty_route_produces_no_message() -> None:
    route = IntroductionRoute(chain=[], hops=0, confidence=0.0, hop_details=[])
    assert build_intro_message(route, "Someone") == ""
