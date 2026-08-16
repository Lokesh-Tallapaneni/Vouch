from __future__ import annotations

from collections import defaultdict

import pytest

from app.models.snapshot import AcquaintanceSeed, NetworkSnapshot
from scripts.generate import PROTAGONIST_ID, build_network, validate_snapshot

#: Matches ``PATH_FINDER_DEFAULT_MAX_HOPS`` in ``scripts.generate`` -- not
#: imported, so a change to that constant has to be a deliberate edit in both
#: places, not something that silently drags these tests along with it.
DEFAULT_MAX_HOPS = 4


def _bfs_distances_from_protagonist(snapshot: NetworkSnapshot) -> dict[str, int]:
    """Shared BFS helper for the distance-property tests below.

    Written independently of ``validate_snapshot``'s own BFS -- the point of
    these tests is to catch a topology regression even if ``validate_snapshot``
    itself were ever weakened or bypassed, not merely to confirm it doesn't
    raise.
    """
    adjacency: dict[str, set[str]] = {person.id: set() for person in snapshot.people}
    for edge in snapshot.acquaintances:
        adjacency[edge.from_id].add(edge.to_id)
        adjacency[edge.to_id].add(edge.from_id)

    distance = {PROTAGONIST_ID: 0}
    frontier = {PROTAGONIST_ID}
    hop = 0
    while frontier:
        hop += 1
        next_frontier: set[str] = set()
        for node in frontier:
            for neighbour in adjacency[node]:
                if neighbour not in distance:
                    distance[neighbour] = hop
                    next_frontier.add(neighbour)
        frontier = next_frontier
    return distance


def _company_nearest_distance(
    snapshot: NetworkSnapshot, distance: dict[str, int]
) -> dict[str, int]:
    current = {e.person_id: e.company for e in snapshot.employments if e.is_current}
    nearest: dict[str, int] = {}
    for person_id, company in current.items():
        person_distance = distance.get(person_id)
        if person_distance is None:
            continue
        if company not in nearest or person_distance < nearest[company]:
            nearest[company] = person_distance
    return nearest


def _best_route_confidence_by_company(snapshot: NetworkSnapshot, max_hops: int) -> dict[str, float]:
    """Highest confidence (product of tie strengths) route from the
    protagonist to any current employee of each company, within ``max_hops``.

    A second, independent implementation of the DP in
    ``scripts.generate._best_route_confidence`` -- duplicated rather than
    imported, for the same reason ``_bfs_distances_from_protagonist`` is: a
    bug in the real implementation should not also be baked into the thing
    checking it.
    """
    adjacency: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for edge in snapshot.acquaintances:
        adjacency[edge.from_id].append((edge.to_id, edge.strength))
        adjacency[edge.to_id].append((edge.from_id, edge.strength))

    best: dict[str, float] = {PROTAGONIST_ID: 1.0}
    for _ in range(max_hops):
        for node, confidence in list(best.items()):
            for neighbour, strength in adjacency[node]:
                candidate = confidence * strength
                if candidate > best.get(neighbour, 0.0):
                    best[neighbour] = candidate

    current = {e.person_id: e.company for e in snapshot.employments if e.is_current}
    by_company: dict[str, float] = {}
    for person_id, confidence in best.items():
        if person_id == PROTAGONIST_ID:
            continue
        company = current.get(person_id)
        if company is None:
            continue
        if company not in by_company or confidence > by_company[company]:
            by_company[company] = confidence
    return by_company


def test_generation_is_deterministic_for_a_fixed_seed() -> None:
    assert build_network(seed=42).model_dump() == build_network(seed=42).model_dump()


def test_different_seeds_produce_different_networks() -> None:
    assert build_network(seed=1).model_dump() != build_network(seed=2).model_dump()


def test_the_protagonist_exists_and_has_a_modest_network() -> None:
    # 4-10, not the looser 3-25 this test originally used: a wider band let a
    # graph where the protagonist had a direct connection into 7 of 8
    # companies pass unnoticed, because raw degree doesn't distinguish "a
    # handful of teammates" from "a hub with one edge per company".
    snapshot = build_network()
    assert any(person.id == PROTAGONIST_ID for person in snapshot.people)
    degree = sum(
        1 for edge in snapshot.acquaintances if PROTAGONIST_ID in (edge.from_id, edge.to_id)
    )
    assert 4 <= degree <= 10, f"protagonist degree {degree} is not demo-friendly"


def test_protagonist_has_a_previous_employer() -> None:
    # This is the demo's own narrative hook -- "someone who left Acme two
    # years ago is your route into Acme" -- so it has to hold at the
    # committed seed, not depend on the 30% dice roll everyone else gets.
    snapshot = build_network()
    previous = [
        record
        for record in snapshot.employments
        if record.person_id == PROTAGONIST_ID and not record.is_current
    ]
    assert len(previous) >= 1, "protagonist has no employment history"


def test_protagonist_neighbours_span_at_most_three_companies() -> None:
    # Relaxed from 2 to 3 in the fix-round-2 pass: the protagonist's own
    # company plus their previous employer already accounts for 2, and that
    # previous-employer door is the whole point -- without room for it, the
    # narrative hook from test_protagonist_has_a_previous_employer above
    # would have nowhere to attach.
    snapshot = build_network()
    current = {e.person_id: e.company for e in snapshot.employments if e.is_current}
    neighbours = {
        edge.to_id if edge.from_id == PROTAGONIST_ID else edge.from_id
        for edge in snapshot.acquaintances
        if PROTAGONIST_ID in (edge.from_id, edge.to_id)
    }
    companies = {current[n] for n in neighbours if n in current}
    assert len(companies) <= 3, f"protagonist's neighbours span {len(companies)} companies"


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


def test_most_edges_are_intra_company() -> None:
    # The failure mode this guards against: flat, company-agnostic teams made
    # 87% of edges cross-company, so "dense within teams" was actually dense
    # *across* companies and the sparse layer never existed at all.
    snapshot = build_network()
    current = {e.person_id: e.company for e in snapshot.employments if e.is_current}
    edges = snapshot.acquaintances
    intra = sum(1 for e in edges if current.get(e.from_id) == current.get(e.to_id))
    assert intra / len(edges) >= 0.60, f"only {intra}/{len(edges)} edges are intra-company"


def test_some_companies_sit_at_a_middle_distance() -> None:
    # Fix-round-1 bug: 7 of 8 companies were one hop away (bimodal: trivially
    # close or nothing). Fix-round-2 overshot the correction: every non-native
    # company sat at *exactly* 4 hops (bimodal again, just the other way).
    # This is the test that would have caught round 2's overshoot: a real
    # topology has companies at every distance in between, not just the
    # extremes.
    snapshot = build_network()
    distance = _bfs_distances_from_protagonist(snapshot)
    nearest = _company_nearest_distance(snapshot, distance)
    middle = [company for company, hops in nearest.items() if hops in (2, 3)]
    assert len(middle) >= 2, f"only {len(middle)} companies are 2-3 hops away (seen: {nearest})"


def test_at_least_one_company_requires_four_or_more_hops() -> None:
    snapshot = build_network()
    distance = _bfs_distances_from_protagonist(snapshot)
    nearest = _company_nearest_distance(snapshot, distance)
    far = [company for company, hops in nearest.items() if hops >= 4]
    assert len(far) >= 1, "no company requires >=4 hops; the *1..5 traversal is decoration"


def test_every_company_has_someone_reachable_within_five_hops() -> None:
    snapshot = build_network()
    distance = _bfs_distances_from_protagonist(snapshot)
    nearest = _company_nearest_distance(snapshot, distance)
    companies = {c.name for c in snapshot.companies}
    unreachable = companies - {company for company, hops in nearest.items() if hops <= 5}
    assert unreachable == set(), f"companies with no one reachable in 5 hops: {unreachable}"


def test_every_company_has_at_least_three_insiders_within_default_hops() -> None:
    # A company page with one or two rows at the default hop limit doesn't
    # look like a product -- this is what fix-round-2's thin pages looked
    # like (some companies had exactly 1 or 2 people reachable at 4 hops).
    snapshot = build_network()
    distance = _bfs_distances_from_protagonist(snapshot)
    current = {e.person_id: e.company for e in snapshot.employments if e.is_current}
    insiders: dict[str, int] = defaultdict(int)
    for person_id, company in current.items():
        if person_id == PROTAGONIST_ID:
            continue
        hops = distance.get(person_id)
        if hops is not None and hops <= DEFAULT_MAX_HOPS:
            insiders[company] += 1
    companies = {c.name for c in snapshot.companies}
    thin = {c for c in companies if insiders.get(c, 0) < 3}
    assert not thin, (
        f"companies with fewer than 3 people reachable in {DEFAULT_MAX_HOPS} hops: {thin}"
    )


def test_best_route_confidence_spans_at_least_two_x_across_companies() -> None:
    # The application's central claim is that route *quality* varies -- a
    # short path through a strong tie should outrank a long path through weak
    # ones. Fix-round-2 had every non-native company at 4 hops with
    # near-identical confidence (0.15-0.18): technically reachable, nothing to
    # rank. This is the test that would have caught it.
    snapshot = build_network()
    by_company = _best_route_confidence_by_company(snapshot, DEFAULT_MAX_HOPS)
    current = {e.person_id: e.company for e in snapshot.employments if e.is_current}
    own_company = current[PROTAGONIST_ID]
    other = [confidence for company, confidence in by_company.items() if company != own_company]
    assert len(other) >= 2, (
        f"only {len(other)} other companies have a route within {DEFAULT_MAX_HOPS} hops"
    )
    spread = max(other) / min(other)
    assert spread >= 2.0, (
        f"confidence spread is only {spread:.2f}x (lowest {min(other):.3f}, "
        f"highest {max(other):.3f}); every route looks about equally good"
    )


def test_validate_accepts_a_generated_snapshot() -> None:
    validate_snapshot(build_network())  # must not raise


# --- Referential integrity: adversarial, not confirmatory -----------------
#
# A test that only checks a clean snapshot passes proves nothing about
# whether the referential-integrity assertions actually fire. Each test here
# takes a real, valid snapshot and deliberately corrupts exactly one
# reference, then asserts ``validate_snapshot`` catches it. The structural
# guarantee ("every reference is always drawn from the same canonical list
# that populates the target collection") lives entirely in how the generator
# happens to be written -- these tests are what would catch a typo or a
# refactor that quietly breaks that guarantee.


def test_validate_rejects_a_dangling_person_id_in_employments() -> None:
    snapshot = build_network()
    snapshot.employments[0].person_id = "nonexistent-person"
    with pytest.raises(AssertionError, match="employments"):
        validate_snapshot(snapshot)


def test_validate_rejects_an_unknown_company_in_employments() -> None:
    snapshot = build_network()
    snapshot.employments[0].company = "Not A Real Company"
    with pytest.raises(AssertionError, match="is not in companies"):
        validate_snapshot(snapshot)


def test_validate_rejects_an_unknown_team_in_memberships() -> None:
    snapshot = build_network()
    snapshot.memberships[0].team = "Not A Real Team"
    with pytest.raises(AssertionError, match="is not in teams"):
        validate_snapshot(snapshot)


def test_validate_rejects_an_unknown_project_in_assignments() -> None:
    snapshot = build_network()
    snapshot.assignments[0].project = "Not A Real Project"
    with pytest.raises(AssertionError, match="is not in projects"):
        validate_snapshot(snapshot)


def test_validate_rejects_an_unknown_skill_in_skill_links() -> None:
    snapshot = build_network()
    snapshot.skill_links[0].skill = "Not A Real Skill"
    with pytest.raises(AssertionError, match="is not in skills"):
        validate_snapshot(snapshot)


def test_validate_rejects_a_dangling_person_id_in_acquaintances() -> None:
    # Appends rather than mutates an existing edge: renaming an endpoint on a
    # real edge risks orphaning whoever that edge was that person's only
    # connection, which would trip the isolation assertion first and mask
    # the referential-integrity check this test targets.
    snapshot = build_network()
    snapshot.acquaintances.append(
        AcquaintanceSeed(
            from_id=PROTAGONIST_ID,
            to_id="nonexistent-person",
            strength=0.5,
            since=2024,
            context="team",
        )
    )
    with pytest.raises(AssertionError, match="acquaintances"):
        validate_snapshot(snapshot)
