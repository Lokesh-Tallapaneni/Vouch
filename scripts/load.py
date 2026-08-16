"""Load the committed snapshot into the graph.

Everything is batched with UNWIND. One row per round trip over Bolt against a
burstable 0.5 vCPU instance is unusably slow -- minutes rather than seconds for
3,000 edges -- and the difference is entirely round-trip latency, not database
work.

Refuses to run while migrations are pending: loading people without a
uniqueness constraint on Person.id silently creates duplicate nodes, and you do
not notice until every path query returns doubled routes.

Usage:
    uv run python -m scripts.load
    uv run python -m scripts.load --reset   # wipe first, with confirmation
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.core.logging import configure_logging, get_logger
from app.core.settings import get_settings
from app.db.client import GraphClient
from app.models.snapshot import NetworkSnapshot
from scripts.generate import SNAPSHOT_PATH
from scripts.migrate import (
    MIGRATIONS_DIR,
    MigrationConflictError,
    SupportsRead,
    discover_migrations,
    fetch_applied,
    find_pending,
)

log = get_logger("load")

BATCH_SIZE = 500

UPSERT_PEOPLE_CYPHER = """
UNWIND $rows AS row
MERGE (p:Person {id: row.id})
  SET p.name = row.name, p.title = row.title,
      p.seniority = row.seniority, p.headline = row.headline
"""

UPSERT_COMPANIES_CYPHER = """
UNWIND $rows AS row
MERGE (c:Company {name: row.name}) SET c.industry = row.industry
"""

UPSERT_TEAMS_CYPHER = "UNWIND $rows AS row MERGE (t:Team {name: row})"
UPSERT_SKILLS_CYPHER = "UNWIND $rows AS row MERGE (s:Skill {name: row})"

UPSERT_PROJECTS_CYPHER = """
UNWIND $rows AS row
MERGE (pr:Project {name: row.name}) SET pr.year = row.year
"""

UPSERT_EMPLOYMENT_CYPHER = """
UNWIND $rows AS row
MATCH (p:Person {id: row.person_id})
MATCH (c:Company {name: row.company})
MERGE (p)-[w:WORKED_AT {from: row.from_year}]->(c)
  SET w.to = row.to_year, w.current = row.is_current
"""

UPSERT_MEMBERSHIP_CYPHER = """
UNWIND $rows AS row
MATCH (p:Person {id: row.person_id})
MATCH (t:Team {name: row.team})
MERGE (p)-[:MEMBER_OF]->(t)
"""

UPSERT_ASSIGNMENT_CYPHER = """
UNWIND $rows AS row
MATCH (p:Person {id: row.person_id})
MATCH (pr:Project {name: row.project})
MERGE (p)-[:WORKS_ON]->(pr)
"""

UPSERT_SKILL_LINK_CYPHER = """
UNWIND $rows AS row
MATCH (p:Person {id: row.person_id})
MATCH (s:Skill {name: row.skill})
MERGE (p)-[h:HAS_SKILL]->(s) SET h.level = row.level
"""

UPSERT_ACQUAINTANCE_CYPHER = """
UNWIND $rows AS row
MATCH (a:Person {id: row.from_id})
MATCH (b:Person {id: row.to_id})
MERGE (a)-[k:KNOWS]->(b)
  SET k.strength = row.strength, k.since = row.since, k.context = row.context
"""

WIPE_CYPHER = "MATCH (n) WHERE NOT n:_Migration DETACH DELETE n"


class SupportsWrite(Protocol):
    async def write(
        self, cypher: str, params: Any = None, *, timeout: float | None = None
    ) -> list[dict[str, Any]]: ...


class PendingMigrationsError(RuntimeError):
    """Migrations are pending; refusing to load data ahead of them."""


@dataclass(frozen=True, slots=True)
class LoadReport:
    nodes_written: int
    relationships_written: int


def batched(items: list[Any], size: int) -> list[list[Any]]:
    """Split into chunks of at most ``size``."""
    return [items[i : i + size] for i in range(0, len(items), size)]


async def _write_batches(
    graph: SupportsWrite, cypher: str, rows: list[Any], batch_size: int, label: str
) -> int:
    written = 0
    for chunk in batched(rows, batch_size):
        await graph.write(cypher, {"rows": chunk}, timeout=120)
        written += len(chunk)
    log.info("loaded %d %s", written, label)
    return written


async def load_snapshot(
    graph: SupportsWrite, snapshot: NetworkSnapshot, *, batch_size: int = BATCH_SIZE
) -> LoadReport:
    """Upsert the whole snapshot. Idempotent -- MERGE throughout, so re-running
    updates rather than duplicating."""
    nodes = 0
    nodes += await _write_batches(
        graph, UPSERT_PEOPLE_CYPHER, [p.model_dump() for p in snapshot.people], batch_size, "people"
    )
    nodes += await _write_batches(
        graph,
        UPSERT_COMPANIES_CYPHER,
        [c.model_dump() for c in snapshot.companies],
        batch_size,
        "companies",
    )
    nodes += await _write_batches(graph, UPSERT_TEAMS_CYPHER, snapshot.teams, batch_size, "teams")
    nodes += await _write_batches(
        graph, UPSERT_SKILLS_CYPHER, snapshot.skills, batch_size, "skills"
    )
    nodes += await _write_batches(
        graph, UPSERT_PROJECTS_CYPHER, snapshot.projects, batch_size, "projects"
    )

    relationships = 0
    for cypher, rows, label in (
        (UPSERT_EMPLOYMENT_CYPHER, snapshot.employments, "employment records"),
        (UPSERT_MEMBERSHIP_CYPHER, snapshot.memberships, "team memberships"),
        (UPSERT_ASSIGNMENT_CYPHER, snapshot.assignments, "project assignments"),
        (UPSERT_SKILL_LINK_CYPHER, snapshot.skill_links, "skill links"),
        (UPSERT_ACQUAINTANCE_CYPHER, snapshot.acquaintances, "acquaintance edges"),
    ):
        relationships += await _write_batches(
            graph, cypher, [r.model_dump() for r in rows], batch_size, label
        )

    return LoadReport(nodes_written=nodes, relationships_written=relationships)


async def ensure_migrations_applied(graph: SupportsRead, migrations_dir: Path) -> None:
    """Refuse to proceed while migrations are pending.

    This is a correctness gate, not a nicety: loading people without the
    uniqueness constraint on ``Person.id`` silently creates duplicate nodes,
    and nothing surfaces it until every path query returns doubled routes --
    by which point the wrong layer is being debugged. Pulled out of ``main()``
    so the gate is exercisable against ``FakeGraph`` in tests instead of only
    live, where an untested guard could quietly stop working.

    Raises:
        PendingMigrationsError: naming every migration id still pending.
        MigrationConflictError: an applied migration's checksum no longer
            matches the file on disk (raised by ``find_pending``).
    """
    pending = find_pending(discover_migrations(migrations_dir), await fetch_applied(graph))
    if pending:
        raise PendingMigrationsError(
            f"refusing to load with {len(pending)} pending migration(s): "
            f"{', '.join(m.id for m in pending)}. "
            "Loading without uniqueness constraints silently duplicates people."
        )


async def main() -> int:
    parser = argparse.ArgumentParser(description="Load the seed snapshot.")
    parser.add_argument("--snapshot", type=Path, default=SNAPSHOT_PATH)
    parser.add_argument("--reset", action="store_true", help="delete all data first")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings)

    snapshot = NetworkSnapshot.model_validate(json.loads(args.snapshot.read_text(encoding="utf-8")))

    async with GraphClient.connect(settings) as graph:
        try:
            await ensure_migrations_applied(graph, MIGRATIONS_DIR)
        except (PendingMigrationsError, MigrationConflictError) as exc:
            # Both are expected operator errors -- a designed refusal, not a
            # crash -- so they get a clean message and exit 1, not a traceback.
            log.error(str(exc))
            return 1

        if args.reset:
            answer = input("Delete all graph data except migration history? [y/N] ")
            if answer.strip().lower() != "y":
                log.info("aborted")
                return 1
            await graph.write(WIPE_CYPHER, timeout=120)
            log.info("graph wiped")

        report = await load_snapshot(graph, snapshot, batch_size=args.batch_size)
        log.info(
            "done: %d nodes, %d relationships",
            report.nodes_written,
            report.relationships_written,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
