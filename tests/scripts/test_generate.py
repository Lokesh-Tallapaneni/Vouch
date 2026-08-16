from __future__ import annotations

from collections import defaultdict

from app.models.snapshot import NetworkSnapshot
from scripts.generate import PROTAGONIST_ID, build_network, validate_snapshot


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


def test_protagonist_neighbours_span_at_most_two_companies() -> None:
    # If the protagonist already knows someone at nearly every company, the
    # "reach into a target company" demo has nothing left to demonstrate.
    snapshot = build_network()
    current = {e.person_id: e.company for e in snapshot.employments if e.is_current}
    neighbours = {
        edge.to_id if edge.from_id == PROTAGONIST_ID else edge.from_id
        for edge in snapshot.acquaintances
        if PROTAGONIST_ID in (edge.from_id, edge.to_id)
    }
    companies = {current[n] for n in neighbours if n in current}
    assert len(companies) <= 2, f"protagonist's neighbours span {len(companies)} companies"


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


def test_multiple_companies_are_more_than_one_hop_from_the_protagonist() -> None:
    # This is the test that would have caught the original bug: 7 of 8
    # companies were one hop away, so the multi-hop path-finder -- the entire
    # graph-database argument -- was never exercised.
    snapshot = build_network()
    distance = _bfs_distances_from_protagonist(snapshot)
    nearest = _company_nearest_distance(snapshot, distance)
    far = [company for company, hops in nearest.items() if hops >= 2]
    assert len(far) >= 3, f"only {len(far)} companies are >=2 hops from the protagonist"


def test_at_least_one_company_requires_a_multi_hop_path() -> None:
    snapshot = build_network()
    distance = _bfs_distances_from_protagonist(snapshot)
    nearest = _company_nearest_distance(snapshot, distance)
    very_far = [company for company, hops in nearest.items() if hops >= 3]
    assert len(very_far) >= 1, "no company requires >=3 hops; the *1..5 traversal is decoration"


def test_not_everyone_is_within_three_hops_of_the_protagonist() -> None:
    snapshot = build_network()
    distance = _bfs_distances_from_protagonist(snapshot)
    all_ids = {p.id for p in snapshot.people}
    within_three = {pid for pid, hops in distance.items() if hops <= 3}
    assert within_three != all_ids, "everyone is within 3 hops; the graph has no real diameter"


def test_every_company_has_someone_reachable_within_five_hops() -> None:
    snapshot = build_network()
    distance = _bfs_distances_from_protagonist(snapshot)
    nearest = _company_nearest_distance(snapshot, distance)
    companies = {c.name for c in snapshot.companies}
    unreachable = companies - {company for company, hops in nearest.items() if hops <= 5}
    assert unreachable == set(), f"companies with no one reachable in 5 hops: {unreachable}"


def test_validate_accepts_a_generated_snapshot() -> None:
    validate_snapshot(build_network())  # must not raise
