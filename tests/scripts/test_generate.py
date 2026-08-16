from __future__ import annotations

from collections import defaultdict

from scripts.generate import PROTAGONIST_ID, build_network, validate_snapshot


def test_generation_is_deterministic_for_a_fixed_seed() -> None:
    assert build_network(seed=42).model_dump() == build_network(seed=42).model_dump()


def test_different_seeds_produce_different_networks() -> None:
    assert build_network(seed=1).model_dump() != build_network(seed=2).model_dump()


def test_the_protagonist_exists_and_has_a_modest_network() -> None:
    snapshot = build_network()
    assert any(person.id == PROTAGONIST_ID for person in snapshot.people)
    degree = sum(
        1 for edge in snapshot.acquaintances if PROTAGONIST_ID in (edge.from_id, edge.to_id)
    )
    assert 3 <= degree <= 25, f"protagonist degree {degree} is not demo-friendly"


def test_no_person_is_isolated() -> None:
    snapshot = build_network()
    connected = {edge.from_id for edge in snapshot.acquaintances}
    connected |= {edge.to_id for edge in snapshot.acquaintances}
    assert {p.id for p in snapshot.people} - connected == set()


def test_some_people_have_a_previous_employer() -> None:
    # Job changes are what create cross-company edges. Without them the graph is
    # an org chart and "reach into a target company" has no answer.
    by_person: dict[str, int] = defaultdict(int)
    for record in build_network().employments:
        by_person[record.person_id] += 1
    assert sum(1 for count in by_person.values() if count > 1) >= 100


def test_tie_strengths_are_probabilities() -> None:
    assert all(0.0 <= edge.strength <= 1.0 for edge in build_network().acquaintances)


def test_validate_accepts_a_generated_snapshot() -> None:
    validate_snapshot(build_network())  # must not raise
