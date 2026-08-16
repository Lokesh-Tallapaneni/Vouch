"""Deterministic synthetic network generator.

No network access, no scraping. All data is invented: for a people-graph
application, generating rather than scraping real professional relationships is
an ethical requirement, not a shortcut.

Topology is generated as a small world, in four layers:

1. Dense inside teams          -- high strength, context "team"
2. Moderate along projects     -- medium strength, context "project"
3. Sparse across companies     -- former colleagues, the long-range edges that
                                  make short paths possible at all
4. A handful of deliberate brokers -- so the broker query has a real answer

Usage:
    uv run python -m scripts.generate            # writes data/snapshot/network.json
    uv run python -m scripts.generate --seed 7
"""

from __future__ import annotations

import argparse
import itertools
import json
import random
from pathlib import Path

from app.models.snapshot import (
    AcquaintanceSeed,
    AssignmentSeed,
    CompanySeed,
    EmploymentSeed,
    MembershipSeed,
    NetworkSnapshot,
    PersonSeed,
    SkillSeed,
)

SNAPSHOT_PATH = Path(__file__).resolve().parent.parent / "data" / "snapshot" / "network.json"

#: The demo always starts from this person, so an evaluator lands somewhere
#: interesting without having to guess a name.
PROTAGONIST_ID = "me"
PROTAGONIST_NAME = "Lokesh Tallapaneni"

POPULATION = 500
CURRENT_YEAR = 2026

COMPANIES = [
    ("Aeromark", "logistics"),
    ("Bluecrest Labs", "biotech"),
    ("Cadence Retail", "retail"),
    ("Dunlin Systems", "infrastructure"),
    ("Everline", "fintech"),
    ("Foundry Works", "manufacturing"),
    ("Greenfield Health", "healthcare"),
    ("Halcyon Media", "media"),
]
TEAMS = [
    "Platform",
    "Payments",
    "Growth",
    "Data",
    "Security",
    "Mobile",
    "Search",
    "Infrastructure",
    "Design",
    "Reliability",
    "Billing",
    "Identity",
    "Analytics",
    "Support",
]
PROJECTS = [
    "Atlas",
    "Beacon",
    "Cobalt",
    "Delta Rewrite",
    "Ember",
    "Fathom",
    "Gateway",
    "Harbour",
    "Ionise",
    "Juniper",
    "Keystone",
    "Lantern",
    "Meridian",
    "Northwind",
    "Orchard",
    "Pinnacle",
    "Quarry",
    "Redshift",
    "Summit",
    "Tidewater",
    "Umbra",
    "Vantage",
    "Wayfinder",
    "Xenon",
    "Yardline",
]
SKILLS = [
    "Python",
    "Go",
    "Rust",
    "TypeScript",
    "Kubernetes",
    "Terraform",
    "PostgreSQL",
    "Cypher",
    "Kafka",
    "Redis",
    "GraphQL",
    "React",
    "Django",
    "FastAPI",
    "Spark",
    "Airflow",
    "dbt",
    "Snowflake",
    "Observability",
    "Incident Response",
    "Threat Modelling",
    "Cryptography",
    "Accessibility",
    "Design Systems",
    "Product Analytics",
    "Experimentation",
    "SEO",
    "Technical Writing",
    "Mentoring",
    "Hiring",
    "Cost Optimisation",
    "Load Testing",
    "CI/CD",
    "Docker",
    "gRPC",
    "Protobuf",
    "Elasticsearch",
    "Neo4j",
    "Pandas",
    "PyTorch",
]
TITLES = [
    "Software Engineer",
    "Senior Software Engineer",
    "Staff Engineer",
    "Engineering Manager",
    "Product Manager",
    "Data Engineer",
    "Data Scientist",
    "Site Reliability Engineer",
    "Security Engineer",
    "Designer",
    "Analyst",
    "Director of Engineering",
]
SENIORITIES = ["junior", "mid", "senior", "staff", "principal"]

# Plausible full names, mixed Indian and international. "Person 1" undercuts a
# people-graph demo badly.
FIRST_NAMES = [
    "Aarav",
    "Priya",
    "Arjun",
    "Meera",
    "Rohan",
    "Ananya",
    "Vikram",
    "Divya",
    "Karthik",
    "Sneha",
    "Ishaan",
    "Nisha",
    "Rahul",
    "Kavya",
    "Aditya",
    "Pooja",
    "Siddharth",
    "Ritika",
    "Manish",
    "Tara",
    "Elena",
    "Marcus",
    "Sofia",
    "Daniel",
    "Amara",
    "Tomas",
    "Ingrid",
    "Hassan",
    "Yuki",
    "Olivia",
    "Mateo",
    "Fatima",
    "Lucas",
    "Chen",
    "Noor",
    "Sven",
    "Grace",
    "Diego",
    "Aisha",
    "Henrik",
]
LAST_NAMES = [
    "Sharma",
    "Reddy",
    "Nair",
    "Iyer",
    "Patel",
    "Menon",
    "Kulkarni",
    "Bose",
    "Rao",
    "Verma",
    "Chowdhury",
    "Pillai",
    "Desai",
    "Joshi",
    "Bhat",
    "Mehta",
    "Gupta",
    "Sinha",
    "Kapoor",
    "Das",
    "Okafor",
    "Lindqvist",
    "Moreau",
    "Rossi",
    "Kowalski",
    "Tanaka",
    "Silva",
    "Fischer",
    "Novak",
    "Haddad",
    "Andersen",
    "Ferreira",
    "Nakamura",
    "Costa",
    "Weber",
    "Larsen",
]


def _build_people(rng: random.Random) -> list[PersonSeed]:
    """Generate people with unique, plausible names."""
    people = [
        PersonSeed(
            id=PROTAGONIST_ID,
            name=PROTAGONIST_NAME,
            title="Software Engineer",
            seniority="mid",
            headline="Building things with graphs.",
        )
    ]
    used: set[str] = {PROTAGONIST_NAME}
    for index in range(1, POPULATION):
        while True:
            name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
            if name not in used:
                used.add(name)
                break
        title = rng.choice(TITLES)
        people.append(
            PersonSeed(
                id=f"p{index:04d}",
                name=name,
                title=title,
                seniority=rng.choice(SENIORITIES),
                headline=f"{title} working on {rng.choice(PROJECTS)}.",
            )
        )
    return people


def _assign_employment(
    rng: random.Random, people: list[PersonSeed]
) -> tuple[list[EmploymentSeed], dict[str, str]]:
    """Give everyone a current employer, and ~30% a previous one.

    Those job changes are the entire basis of "reach into a target company":
    without employment history the graph is an org chart.
    """
    employments: list[EmploymentSeed] = []
    current_company: dict[str, str] = {}
    names = [name for name, _ in COMPANIES]

    for person in people:
        company = rng.choice(names)
        current_company[person.id] = company
        started = rng.randint(CURRENT_YEAR - 6, CURRENT_YEAR - 1)
        employments.append(
            EmploymentSeed(
                person_id=person.id,
                company=company,
                from_year=started,
                to_year=None,
                is_current=True,
            )
        )
        if rng.random() < 0.30:
            previous = rng.choice([n for n in names if n != company])
            left = started - rng.randint(1, 2)
            employments.append(
                EmploymentSeed(
                    person_id=person.id,
                    company=previous,
                    from_year=left - rng.randint(1, 4),
                    to_year=left,
                    is_current=False,
                )
            )
    return employments, current_company


def _tie_strength(
    rng: random.Random, *, same_team: bool, shared_projects: int, overlap_years: int
) -> float:
    """The one place a tie strength is computed. Documented in the README so the
    number is never magic."""
    strength = (
        0.15
        + 0.35 * (1.0 if same_team else 0.0)
        + 0.20 * (min(shared_projects, 2) / 2)
        + 0.20 * (min(overlap_years, 3) / 3)
        + 0.10 * rng.random()
    )
    return round(min(1.0, strength), 3)


def build_network(seed: int = 42) -> NetworkSnapshot:
    """Build the whole network deterministically."""
    rng = random.Random(seed)

    people = _build_people(rng)
    employments, current_company = _assign_employment(rng, people)

    team_of = {person.id: rng.choice(TEAMS) for person in people}
    memberships = [MembershipSeed(person_id=pid, team=team) for pid, team in team_of.items()]

    projects_of: dict[str, list[str]] = {
        person.id: rng.sample(PROJECTS, rng.randint(1, 3)) for person in people
    }
    assignments = [
        AssignmentSeed(person_id=pid, project=project)
        for pid, projects in projects_of.items()
        for project in projects
    ]

    skill_links = [
        SkillSeed(
            person_id=person.id, skill=skill, level=rng.choice(["working", "strong", "expert"])
        )
        for person in people
        for skill in rng.sample(SKILLS, rng.randint(2, 5))
    ]

    edges: dict[tuple[str, str], AcquaintanceSeed] = {}

    def link(a: str, b: str, context: str, strength: float) -> None:
        if a == b:
            return
        key = (a, b) if a < b else (b, a)
        if key in edges:
            return
        edges[key] = AcquaintanceSeed(
            from_id=key[0],
            to_id=key[1],
            strength=strength,
            since=rng.randint(CURRENT_YEAR - 8, CURRENT_YEAR),
            context=context,
        )

    # 1. Dense within teams.
    by_team: dict[str, list[str]] = {}
    for pid, team in team_of.items():
        by_team.setdefault(team, []).append(pid)
    for members in by_team.values():
        for a, b in itertools.combinations(members, 2):
            if rng.random() < 0.25:
                link(
                    a,
                    b,
                    "team",
                    _tie_strength(rng, same_team=True, shared_projects=1, overlap_years=2),
                )

    # 2. Moderate along shared projects.
    by_project: dict[str, list[str]] = {}
    for pid, projects in projects_of.items():
        for project in projects:
            by_project.setdefault(project, []).append(pid)
    for members in by_project.values():
        for a, b in itertools.combinations(members, 2):
            if rng.random() < 0.10:
                link(
                    a,
                    b,
                    "project",
                    _tie_strength(rng, same_team=False, shared_projects=2, overlap_years=2),
                )

    # 3. Sparse across companies -- former colleagues. These long-range edges
    #    are what make any short path exist between distant parts of the graph.
    ids = [person.id for person in people]
    for _ in range(320):
        a, b = rng.sample(ids, 2)
        if current_company[a] != current_company[b]:
            link(
                a,
                b,
                "former-colleague",
                _tie_strength(rng, same_team=False, shared_projects=0, overlap_years=1),
            )

    # 4. Deliberate brokers, so Q3 returns a meaningful answer rather than noise.
    for broker in rng.sample(ids, 5):
        for other in rng.sample(ids, 6):
            if team_of[broker] != team_of[other]:
                link(
                    broker,
                    other,
                    "former-colleague",
                    _tie_strength(rng, same_team=False, shared_projects=0, overlap_years=2),
                )

    # 5. Guarantee nobody is isolated -- an isolated person renders an empty
    #    profile and makes the app look broken.
    connected = {edge.from_id for edge in edges.values()} | {edge.to_id for edge in edges.values()}
    for person in people:
        if person.id not in connected:
            link(person.id, rng.choice([i for i in ids if i != person.id]), "team", 0.3)

    return NetworkSnapshot(
        people=people,
        companies=[CompanySeed(name=name, industry=industry) for name, industry in COMPANIES],
        teams=TEAMS,
        projects=[
            {"name": name, "year": rng.randint(CURRENT_YEAR - 4, CURRENT_YEAR)} for name in PROJECTS
        ],
        skills=SKILLS,
        employments=employments,
        memberships=memberships,
        assignments=assignments,
        skill_links=skill_links,
        acquaintances=list(edges.values()),
    )


def validate_snapshot(snapshot: NetworkSnapshot) -> None:
    """Fail generation rather than discover a dead demo at hour ten.

    Raises:
        AssertionError: if the topology would make the demo queries boring or empty.
    """
    ids = {person.id for person in snapshot.people}
    connected = {e.from_id for e in snapshot.acquaintances} | {
        e.to_id for e in snapshot.acquaintances
    }
    assert ids - connected == set(), "some people are isolated"
    assert PROTAGONIST_ID in ids, "protagonist missing"

    adjacency: dict[str, set[str]] = {pid: set() for pid in ids}
    for edge in snapshot.acquaintances:
        adjacency[edge.from_id].add(edge.to_id)
        adjacency[edge.to_id].add(edge.from_id)

    # Breadth-first to depth 4 from the protagonist.
    seen, frontier = {PROTAGONIST_ID}, {PROTAGONIST_ID}
    for _ in range(4):
        frontier = {n for node in frontier for n in adjacency[node]} - seen
        seen |= frontier

    current = {e.person_id: e.company for e in snapshot.employments if e.is_current}
    reachable_companies = {current[pid] for pid in seen if pid in current}
    assert len(reachable_companies) >= 3, (
        f"only {len(reachable_companies)} companies reachable within 4 hops; "
        "the company-reach demo would be thin"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the seed network.")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=SNAPSHOT_PATH)
    args = parser.parse_args()

    snapshot = build_network(args.seed)
    validate_snapshot(snapshot)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(snapshot.model_dump(), indent=2, sort_keys=True), encoding="utf-8"
    )
    print(
        f"wrote {args.out}: {len(snapshot.people)} people, "
        f"{len(snapshot.acquaintances)} acquaintance edges, "
        f"{len(snapshot.employments)} employment records"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
