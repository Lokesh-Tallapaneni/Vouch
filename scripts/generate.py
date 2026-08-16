"""Deterministic synthetic network generator.

No network access, no scraping. All data is invented: for a people-graph
application, generating rather than scraping real professional relationships is
an ethical requirement, not a shortcut.

Topology is generated as a small world, in five layers:

1. Dense inside teams          -- high strength, context "team". Teams belong to
                                  a single company (see ``_assign_teams``), so this
                                  layer is *always* intra-company by construction.
2. Moderate along projects     -- medium strength, context "project". Projects are
                                  company-agnostic, so this layer contributes most
                                  of the graph's intentional cross-company mixing.
3. Sparse across companies     -- former colleagues, the long-range edges that
                                  make short paths possible at all
4. A handful of deliberate brokers -- so the broker query has a real answer
5. A hand-curated protagonist  -- kept deliberately modest (see ``_curate_protagonist``)
                                  so the demo has somewhere to grow from

Usage:
    uv run python -m scripts.generate            # writes data/snapshot/network.json
    uv run python -m scripts.generate --seed 7
"""

from __future__ import annotations

import argparse
import itertools
import json
import random
from collections import defaultdict
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

#: How many teams each company is split into. Teams are company-scoped (see
#: ``_assign_teams``) -- this constant is what keeps team sizes big enough for a
#: "dense within team" layer to mean something instead of dissolving into pairs.
NUM_TEAMS_PER_COMPANY = 5

#: Edge probabilities per layer. Tuned (by simulating BFS distance from the
#: protagonist and the intra/cross-company split at seed 42, then adjusting) so
#: the whole graph lands at a mean degree of roughly 10-12 with >=90%
#: intra-company edges -- dense enough to browse, sparse enough that distance
#: between companies is real rather than decorative. Team edges are the
#: majority layer and are always intra-company (see ``_assign_teams``); project
#: edges are the main source of *intentional* cross-company mixing, so they are
#: kept nearly two orders of magnitude rarer than team edges -- company size
#: (~62 people) is small, but project membership pools are large (~40 people
#: per project, drawn from the whole company-agnostic population), so even a
#: small probability there produces a lot of cross-company noise if left high.
P_TEAM_EDGE = 0.80
P_PROJECT_EDGE = 0.008

#: Layer 3: random cross-company sampling attempts. This is deliberately a
#: small fraction of the population -- these are the long-range weak ties that
#: make any short path exist between distant parts of the graph, and "sparse"
#: only means something if the count stays small. Tuned down from an earlier
#: pass that made *every* company reachable within 3 hops -- with the
#: protagonist's own cross-company door now guaranteed (see
#: ``_ensure_protagonist_previous_employer``), the general layers only need to
#: supply the *rest* of the spread: some companies at a middling 2-3 hops, at
#: least one held out past 4, each retaining a real path-finder result.
FORMER_COLLEAGUE_SAMPLE_ATTEMPTS = 10

#: Layer 4: a handful of people who deliberately bridge a few teams, so "who
#: connects unrelated parts of the org" has a real answer -- but few enough
#: that they do not become a shortcut between every pair of companies.
BROKER_COUNT = 2
BROKER_LINKS = 1

#: The protagonist is hand-curated (layer 5), not run through the general random
#: layers, so their network stays small and interpretable: a handful of
#: teammates plus a couple of contacts at their previous employer -- their
#: employment history is guaranteed (see ``_ensure_protagonist_previous_employer``),
#: not left to the 30% dice roll everyone else gets, because it is the demo's
#: own narrative hook: "someone who left Acme two years ago is your route into
#: Acme" has to hold at the committed seed.
PROTAGONIST_TEAM_LINKS = (4, 6)
PROTAGONIST_MIN_DEGREE = 4
PROTAGONIST_MAX_DEGREE = 10

#: How many contacts the protagonist keeps at their previous employer, and at
#: what strength. Explicit and deliberately varied -- one strong, one
#: middling, optionally one weak -- rather than drawn from ``_tie_strength``,
#: so the best-route confidence into this company is visibly higher than into
#: a company with no shared history. That gap is what makes "ranked by
#: confidence" mean something instead of a column of near-identical numbers.
PROTAGONIST_FORMER_COLLEAGUE_COUNTS = (2, 3)
PROTAGONIST_FORMER_COLLEAGUE_STRENGTHS = (0.88, 0.5, 0.32)

#: How many companies the protagonist's *direct* neighbours may span: their
#: own plus their previous employer. Kept tight -- a wider spread here is what
#: caused the original bug (nearly every company one hop away).
PROTAGONIST_MAX_NEIGHBOUR_COMPANIES = 3

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


def _ensure_protagonist_previous_employer(
    rng: random.Random, employments: list[EmploymentSeed], current_company: dict[str, str]
) -> str:
    """Guarantee the protagonist has a previous employer, deterministically.

    Everyone else's employment history is a 30% dice roll (see
    ``_assign_employment``), which is fine for a population statistic but not
    for the one person the demo is written around: "someone who left Acme two
    years ago is your route into Acme" is the narrative the app opens on, and
    it must hold at the committed seed rather than depend on how the RNG
    happened to land. If the roll already gave the protagonist a previous
    employer, that stands; only a missing one is synthesized.
    """
    for record in employments:
        if record.person_id == PROTAGONIST_ID and not record.is_current:
            return record.company

    names = [name for name, _ in COMPANIES]
    current_index, current_record = next(
        (i, r) for i, r in enumerate(employments) if r.person_id == PROTAGONIST_ID and r.is_current
    )
    previous = rng.choice([n for n in names if n != current_record.company])
    left = current_record.from_year - rng.randint(1, 2)
    employments.insert(
        current_index + 1,
        EmploymentSeed(
            person_id=PROTAGONIST_ID,
            company=previous,
            from_year=left - rng.randint(1, 4),
            to_year=left,
            is_current=False,
        ),
    )
    return previous


def _assign_teams(
    rng: random.Random, people: list[PersonSeed], current_company: dict[str, str]
) -> dict[str, str]:
    """Assign each person a team that is scoped to their current employer.

    This is the fix for the failure mode where an "intra-team" edge was
    silently a cross-company edge: a flat, company-agnostic team list means two
    people on "Platform" could work for different employers entirely, so the
    "dense within teams" layer was actually dense *across* companies. Scoping
    the team name to the company (``"Everline · Platform"``) makes intra-team
    membership imply intra-company membership by construction, not by luck.
    """
    team_of: dict[str, str] = {}
    for person in people:
        team_index = rng.randrange(NUM_TEAMS_PER_COMPANY)
        team_of[person.id] = f"{current_company[person.id]} · {TEAMS[team_index]}"
    return team_of


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


def _curate_protagonist(
    rng: random.Random,
    *,
    team_mates: list[str],
    link: _Linker,
) -> None:
    """Hand-wire the protagonist's network instead of running them through the
    general random layers.

    The protagonist is the demo's starting point. A random draw from the same
    distributions as everyone else risks landing them a broker-sized network
    (or, worse, actually making them a sampled broker) and defeating the
    premise that reaching a distant company takes real navigation. So their
    edges are built explicitly: a handful of teammates (always intra-company,
    since teams are company-scoped) plus, only if they have one, a couple of
    contacts at their previous employer -- the one deliberate cross-company
    door this person opens, and no more than one.
    """
    team_pool = [pid for pid in team_mates if pid != PROTAGONIST_ID]
    low, high = PROTAGONIST_TEAM_LINKS
    count = min(rng.randint(low, high), len(team_pool))
    for mate in rng.sample(team_pool, count):
        link(
            PROTAGONIST_ID,
            mate,
            "team",
            _tie_strength(rng, same_team=True, shared_projects=1, overlap_years=2),
        )


def _curate_protagonist_former_colleagues(
    rng: random.Random,
    *,
    previous_company: str,
    current_company: dict[str, str],
    people_ids: list[str],
    link: _Linker,
    existing_degree: int,
) -> None:
    """The protagonist's deliberate doorway into their previous employer.

    Strengths are explicit and deliberately varied (see
    ``PROTAGONIST_FORMER_COLLEAGUE_STRENGTHS``), not drawn from
    ``_tie_strength``, so the best route into this company reads as
    meaningfully more confident than a route into a company the protagonist
    has no history with. Capped so it never pushes the protagonist past
    ``PROTAGONIST_MAX_DEGREE`` or introduces a third company into their
    neighbourhood -- see the module docstring on why that boundary matters.
    """
    room = PROTAGONIST_MAX_DEGREE - existing_degree
    if room <= 0:
        return
    candidates = [
        pid
        for pid in people_ids
        if pid != PROTAGONIST_ID and current_company[pid] == previous_company
    ]
    if not candidates:
        return
    low, high = PROTAGONIST_FORMER_COLLEAGUE_COUNTS
    count = min(rng.randint(low, high), len(candidates), room)
    contacts = rng.sample(candidates, count)
    for contact, strength in zip(
        contacts, PROTAGONIST_FORMER_COLLEAGUE_STRENGTHS[:count], strict=True
    ):
        link(PROTAGONIST_ID, contact, "former-colleague", strength)


class _Linker:
    """Dedupe and record acquaintance edges as they are proposed.

    A plain function closure would work too, but naming the type makes the
    signature readable at the call sites above instead of everyone writing
    ``Callable[[str, str, str, float], None]``.
    """

    def __init__(self, rng: random.Random) -> None:
        self._rng = rng
        self.edges: dict[tuple[str, str], AcquaintanceSeed] = {}

    def __call__(self, a: str, b: str, context: str, strength: float) -> None:
        if a == b:
            return
        key = (a, b) if a < b else (b, a)
        if key in self.edges:
            return
        self.edges[key] = AcquaintanceSeed(
            from_id=key[0],
            to_id=key[1],
            strength=strength,
            since=self._rng.randint(CURRENT_YEAR - 8, CURRENT_YEAR),
            context=context,
        )

    def degree(self, person_id: str) -> int:
        return sum(1 for a, b in self.edges if person_id in (a, b))

    def neighbours(self, person_id: str) -> set[str]:
        result: set[str] = set()
        for a, b in self.edges:
            if a == person_id:
                result.add(b)
            elif b == person_id:
                result.add(a)
        return result


def build_network(seed: int = 42) -> NetworkSnapshot:
    """Build the whole network deterministically."""
    rng = random.Random(seed)

    people = _build_people(rng)
    employments, current_company = _assign_employment(rng, people)
    protagonist_previous = _ensure_protagonist_previous_employer(rng, employments, current_company)
    team_of = _assign_teams(rng, people, current_company)
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

    link = _Linker(rng)

    # 1. Dense within teams. Teams are company-scoped (see ``_assign_teams``),
    #    so every edge here is intra-company by construction. The protagonist
    #    is excluded -- their team edges are hand-curated below.
    by_team: dict[str, list[str]] = {}
    for pid, team in team_of.items():
        by_team.setdefault(team, []).append(pid)
    for members in by_team.values():
        generic_members = [pid for pid in members if pid != PROTAGONIST_ID]
        for a, b in itertools.combinations(generic_members, 2):
            if rng.random() < P_TEAM_EDGE:
                link(
                    a,
                    b,
                    "team",
                    _tie_strength(rng, same_team=True, shared_projects=1, overlap_years=2),
                )

    # 2. Moderate along shared projects. Projects are company-agnostic, so this
    #    is the layer that does most of the *intentional* cross-company mixing
    #    -- kept an order of magnitude sparser than the team layer so it stays
    #    a minority of the graph's edges.
    by_project: dict[str, list[str]] = {}
    for pid, projects in projects_of.items():
        for project in projects:
            by_project.setdefault(project, []).append(pid)
    for members in by_project.values():
        generic_members = [pid for pid in members if pid != PROTAGONIST_ID]
        for a, b in itertools.combinations(generic_members, 2):
            if rng.random() < P_PROJECT_EDGE:
                link(
                    a,
                    b,
                    "project",
                    _tie_strength(rng, same_team=False, shared_projects=2, overlap_years=2),
                )

    # 3. Sparse across companies -- former colleagues. These long-range edges
    #    are what make any short path exist between distant parts of the
    #    graph. The protagonist is excluded from this general sampling; their
    #    one cross-company door is hand-curated below.
    generic_ids = [person.id for person in people if person.id != PROTAGONIST_ID]
    for _ in range(FORMER_COLLEAGUE_SAMPLE_ATTEMPTS):
        a, b = rng.sample(generic_ids, 2)
        if current_company[a] != current_company[b]:
            link(
                a,
                b,
                "former-colleague",
                _tie_strength(rng, same_team=False, shared_projects=0, overlap_years=1),
            )

    # 4. Deliberate brokers, so Q3 returns a meaningful answer rather than
    #    noise. Drawn from the generic pool -- the protagonist never becomes,
    #    or is directly wired to, a broker; that would defeat the premise that
    #    their own network is modest.
    for broker in rng.sample(generic_ids, BROKER_COUNT):
        for other in rng.sample(generic_ids, BROKER_LINKS):
            if team_of[broker] != team_of[other]:
                link(
                    broker,
                    other,
                    "former-colleague",
                    _tie_strength(rng, same_team=False, shared_projects=0, overlap_years=2),
                )

    # 5. The protagonist: hand-curated, not drawn from the layers above. See
    #    ``_curate_protagonist`` for why.
    _curate_protagonist(
        rng,
        team_mates=by_team[team_of[PROTAGONIST_ID]],
        link=link,
    )
    _curate_protagonist_former_colleagues(
        rng,
        previous_company=protagonist_previous,
        current_company=current_company,
        people_ids=generic_ids,
        link=link,
        existing_degree=link.degree(PROTAGONIST_ID),
    )
    # The protagonist might have landed on a team too small to reach the
    # minimum on its own (rare, but possible for small companies) -- top up
    # from the rest of their own company rather than leave them under the
    # demo-friendly floor.
    if link.degree(PROTAGONIST_ID) < PROTAGONIST_MIN_DEGREE:
        own_company = current_company[PROTAGONIST_ID]
        backup_pool = [
            pid
            for pid in generic_ids
            if current_company[pid] == own_company and pid not in link.neighbours(PROTAGONIST_ID)
        ]
        needed = PROTAGONIST_MIN_DEGREE - link.degree(PROTAGONIST_ID)
        for mate in rng.sample(backup_pool, min(needed, len(backup_pool))):
            link(
                PROTAGONIST_ID,
                mate,
                "team",
                _tie_strength(rng, same_team=True, shared_projects=0, overlap_years=1),
            )

    # 6. Guarantee nobody is isolated -- an isolated person renders an empty
    #    profile and makes the app look broken. The protagonist is already
    #    connected by construction, so this only ever fires for everyone else.
    all_ids = [person.id for person in people]
    connected = {a for a, _ in link.edges} | {b for _, b in link.edges}
    for person in people:
        if person.id not in connected:
            link(person.id, rng.choice([i for i in all_ids if i != person.id]), "team", 0.3)

    return NetworkSnapshot(
        people=people,
        companies=[CompanySeed(name=name, industry=industry) for name, industry in COMPANIES],
        teams=sorted(
            f"{company} · {team}"
            for company, _ in COMPANIES
            for team in TEAMS[:NUM_TEAMS_PER_COMPANY]
        ),
        projects=[
            {"name": name, "year": rng.randint(CURRENT_YEAR - 4, CURRENT_YEAR)} for name in PROJECTS
        ],
        skills=SKILLS,
        employments=employments,
        memberships=memberships,
        assignments=assignments,
        skill_links=skill_links,
        acquaintances=list(link.edges.values()),
    )


#: The hop limit the default company page traverses at. Two assertions below
#: (insiders-per-company, confidence spread) are evaluated at exactly this
#: bound because it is what an evaluator actually sees, not an abstract
#: "eventually reachable" -- a company can be technically reachable within 5
#: hops (a different, looser assertion below) and still render an empty page
#: at the default depth.
PATH_FINDER_DEFAULT_MAX_HOPS = 4


def _strength_adjacency(snapshot: NetworkSnapshot) -> dict[str, list[tuple[str, float]]]:
    """Undirected adjacency carrying tie strength, for confidence routing."""
    adjacency: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for edge in snapshot.acquaintances:
        adjacency[edge.from_id].append((edge.to_id, edge.strength))
        adjacency[edge.to_id].append((edge.from_id, edge.strength))
    return adjacency


def _best_route_confidence(
    adjacency: dict[str, list[tuple[str, float]]], start: str, max_hops: int
) -> dict[str, tuple[float, int]]:
    """Highest-confidence route from ``start`` to every node reachable within
    ``max_hops``, where confidence is the product of tie strengths along the
    path -- a chain of independent probabilities, the same model the
    application's path-finder ranks routes by. Returns
    ``{node: (confidence, hops)}``, ``hops`` being the fewest hops needed to
    achieve that confidence (a short strong path beats a long strong one).

    Implemented as bounded-hop relaxation: ``layers[h]`` holds the best
    confidence reachable using *at most* ``h`` edges, so it is monotonically
    non-decreasing in ``h`` and the DP is exact for the hop bound, unlike a
    plain BFS shortest-path which would ignore stronger longer routes.
    """
    layers: list[dict[str, float]] = [{start: 1.0}]
    for _ in range(max_hops):
        previous = layers[-1]
        layer = dict(previous)
        for node, confidence in previous.items():
            for neighbour, strength in adjacency[node]:
                candidate = confidence * strength
                if candidate > layer.get(neighbour, 0.0):
                    layer[neighbour] = candidate
        layers.append(layer)

    final = layers[-1]
    routes: dict[str, tuple[float, int]] = {}
    for node, confidence in final.items():
        if node == start:
            continue
        hops = next(h for h, layer in enumerate(layers) if layer.get(node, 0.0) >= confidence)
        routes[node] = (confidence, hops)
    return routes


def validate_snapshot(snapshot: NetworkSnapshot) -> None:
    """Fail generation rather than discover a dead demo at hour ten.

    Round 1's only distance-related assertion (">=3 companies reachable
    within 4 hops") passed on a graph where 7 of 8 companies were *one* hop
    away -- reachability doesn't distinguish "trivially close" from "properly
    distant". Round 2 fixed the collapse but overshot: cross-company reach
    became so sparse that every non-native company sat at exactly 4 hops with
    near-identical low confidence, so there was nothing for "ranked by route
    quality" to rank. These assertions pin a *spread* -- some companies close,
    some far, confidence visibly different -- because that spread is the
    thing route-ranking exists to demonstrate.

    Raises:
        AssertionError: if the topology would make the demo queries boring,
            empty, thin, or make every route look equally (un)confident.
    """
    ids = {person.id for person in snapshot.people}
    edges = snapshot.acquaintances
    connected = {e.from_id for e in edges} | {e.to_id for e in edges}
    assert ids - connected == set(), "some people are isolated -- an empty, broken-looking profile"
    assert PROTAGONIST_ID in ids, "protagonist missing"

    adjacency: dict[str, set[str]] = {pid: set() for pid in ids}
    for edge in edges:
        adjacency[edge.from_id].add(edge.to_id)
        adjacency[edge.to_id].add(edge.from_id)

    # BFS distances from the protagonist to every reachable person.
    distance: dict[str, int] = {PROTAGONIST_ID: 0}
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

    current = {e.person_id: e.company for e in snapshot.employments if e.is_current}

    # For each company, the distance to its *nearest* current employee -- the
    # best case for "how many hops to reach someone at this company".
    company_nearest: dict[str, int] = {}
    for person_id, company in current.items():
        person_distance = distance.get(person_id)
        if person_distance is None:
            continue
        if company not in company_nearest or person_distance < company_nearest[company]:
            company_nearest[company] = person_distance

    companies = {c.name for c in snapshot.companies}

    # The middle distances: companies that are neither trivially close (0-1
    # hops -- the protagonist's own employer and their curated previous one)
    # nor stuck at the far edge. Without this band, "ranked by distance" has
    # nothing to rank between "here" and "as far as possible".
    middle_distance = [c for c, d in company_nearest.items() if d in (2, 3)]
    assert len(middle_distance) >= 2, (
        f"only {len(middle_distance)} companies are 2-3 hops from the protagonist "
        f"(distances seen: {company_nearest}); the graph is bimodal -- trivially "
        "close or maximally far, nothing in between -- so there is no real spread "
        "for a distance-based ranking to show"
    )

    genuinely_far = [c for c, d in company_nearest.items() if d >= 4]
    assert len(genuinely_far) >= 1, (
        "no company requires >=4 hops to reach from the protagonist; "
        "the *1..5 traversal bound in the Cypher query would be decoration"
    )

    protagonist_degree = len(adjacency[PROTAGONIST_ID])
    assert PROTAGONIST_MIN_DEGREE <= protagonist_degree <= PROTAGONIST_MAX_DEGREE, (
        f"protagonist degree {protagonist_degree} is outside the demo-friendly "
        f"{PROTAGONIST_MIN_DEGREE}-{PROTAGONIST_MAX_DEGREE} range"
    )

    protagonist_companies = {
        current[neighbour] for neighbour in adjacency[PROTAGONIST_ID] if neighbour in current
    }
    assert len(protagonist_companies) <= PROTAGONIST_MAX_NEIGHBOUR_COMPANIES, (
        f"the protagonist's direct neighbours span {len(protagonist_companies)} "
        f"companies (limit {PROTAGONIST_MAX_NEIGHBOUR_COMPANIES}); if they already "
        "know someone almost everywhere there is nothing left for the demo to "
        "demonstrate"
    )

    # At the default page depth, every company needs enough people to look
    # like a real page -- one or two rows reads as broken, not sparse.
    insiders_within_default_hops: dict[str, int] = defaultdict(int)
    for person_id, company in current.items():
        if person_id == PROTAGONIST_ID:
            continue
        person_distance = distance.get(person_id)
        if person_distance is not None and person_distance <= PATH_FINDER_DEFAULT_MAX_HOPS:
            insiders_within_default_hops[company] += 1
    thin_companies = {c for c in companies if insiders_within_default_hops.get(c, 0) < 3}
    assert not thin_companies, (
        f"companies with fewer than 3 people reachable within "
        f"{PATH_FINDER_DEFAULT_MAX_HOPS} hops: {sorted(thin_companies)}; "
        "that page would render as one or two rows, not a real result set"
    )

    # The application's central claim is that route *quality* varies -- a
    # short path through a strong tie should visibly outrank a long path
    # through weak ones. If every company's best route scores about the same,
    # there is nothing for that ranking to demonstrate.
    strength_adjacency = _strength_adjacency(snapshot)
    routes = _best_route_confidence(
        strength_adjacency, PROTAGONIST_ID, PATH_FINDER_DEFAULT_MAX_HOPS
    )
    company_best_confidence: dict[str, float] = {}
    for person_id, (confidence, _hops) in routes.items():
        route_company = current.get(person_id)
        if route_company is None:
            continue
        if (
            route_company not in company_best_confidence
            or confidence > company_best_confidence[route_company]
        ):
            company_best_confidence[route_company] = confidence
    own_company = current[PROTAGONIST_ID]
    other_confidences = [v for c, v in company_best_confidence.items() if c != own_company]
    assert len(other_confidences) >= 2, (
        f"only {len(other_confidences)} companies other than the protagonist's own have "
        f"any route within {PATH_FINDER_DEFAULT_MAX_HOPS} hops; there is nothing to rank"
    )
    confidence_spread = max(other_confidences) / min(other_confidences)
    assert confidence_spread >= 2.0, (
        f"best-route confidence across companies spans only {confidence_spread:.2f}x "
        f"(lowest {min(other_confidences):.3f}, highest {max(other_confidences):.3f}); "
        "every route looks about equally good, so ranking by confidence has "
        "nothing meaningful to demonstrate"
    )

    intra_company_edges = sum(1 for e in edges if current.get(e.from_id) == current.get(e.to_id))
    intra_fraction = intra_company_edges / len(edges)
    assert intra_fraction >= 0.60, (
        f"only {intra_company_edges}/{len(edges)} edges ({intra_fraction:.0%}) are "
        "intra-company; the 'sparse across companies' layer has swallowed the graph"
    )

    unreachable_within_five = companies - {c for c, d in company_nearest.items() if d <= 5}
    assert unreachable_within_five == set(), (
        f"companies with no employee within 5 hops of the protagonist: "
        f"{sorted(unreachable_within_five)}; that query would be a dead end"
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
