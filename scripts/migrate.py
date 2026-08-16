"""Versioned schema and data migrations for the graph.

CognoDB is schema-optional, but constraints, indexes and the shape of the data
are still state that must be reproducible from an empty instance. Migrations
are numbered, checksummed, and recorded in the graph itself.

The checksum check is what makes this a migration *system* rather than a folder
of scripts: editing a migration that has already been applied aborts loudly,
because the database can no longer be reproduced from the files on disk.

Usage:
    uv run python -m scripts.migrate            # apply everything pending
    uv run python -m scripts.migrate --status   # what is applied, and when
    uv run python -m scripts.migrate --dry-run  # what would run, change nothing
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from app.core.logging import configure_logging, get_logger
from app.core.settings import get_settings
from app.db.client import GraphClient

log = get_logger("migrate")

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"

#: Migration state lives in the graph -- the natural place for it, and it means
#: a fresh clone pointed at an existing instance knows what has run.
RECORD_MIGRATION_CYPHER = """
MERGE (m:_Migration {id: $id})
  SET m.checksum    = $checksum,
      m.applied_at  = datetime(),
      m.duration_ms = $duration_ms
"""

#: Returns the native temporal, not a string. CognoDB's toString() on a
#: temporal produces a struct dump ("{{2026 8 16} {13 19 42 769114387} 0}"),
#: not ISO-8601 -- GraphClient already coerces the driver's native temporal to
#: a Python datetime when materialising rows, so formatting happens in Python
#: (see _format_applied_at) instead of asking the database to stringify it.
APPLIED_MIGRATIONS_CYPHER = """
MATCH (m:_Migration)
RETURN m.id AS id, m.checksum AS checksum, m.applied_at AS applied_at
ORDER BY id
"""

_NUMERIC_PREFIX = re.compile(r"^(\d+)_")


class MigrationConflictError(RuntimeError):
    """An already-applied migration was edited on disk."""


class SupportsRead(Protocol):
    """Structural type for anything that can answer a read query.

    Lets ``fetch_applied`` -- and the pending-migrations guard the loader
    builds on it -- be exercised against ``FakeGraph`` in tests, rather than
    depending on the concrete ``GraphClient`` class.
    """

    async def read(
        self, cypher: str, params: Mapping[str, Any] | None = None, *, timeout: float | None = None
    ) -> list[dict[str, Any]]: ...


@dataclass(frozen=True, slots=True)
class Migration:
    id: str
    path: Path
    statements: list[str]
    checksum: str


def checksum_of(text: str) -> str:
    """SHA-256 of a migration's contents, newline-normalised.

    Normalising line endings first means a Windows checkout and a Linux
    container agree, rather than every file looking edited after a clone.
    """
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def split_statements(text: str) -> list[str]:
    """Split a .cypher file into individual statements.

    Each runs in its own transaction, so they must be separated here: constraint
    and index creation cannot share a transaction with data writes on a
    Bolt-protocol database.
    """
    without_comments = "\n".join(
        line for line in text.splitlines() if not line.strip().startswith("//")
    )
    return [stmt.strip() for stmt in without_comments.split(";") if stmt.strip()]


def discover_migrations(directory: Path) -> list[Migration]:
    """Read every .cypher file, ordered by numeric prefix.

    Sorted numerically rather than lexicographically, so 0010 follows 0002
    instead of preceding it.
    """
    migrations: list[Migration] = []
    for path in directory.glob("*.cypher"):
        text = path.read_text(encoding="utf-8")
        migrations.append(
            Migration(
                id=path.stem,
                path=path,
                statements=split_statements(text),
                checksum=checksum_of(text),
            )
        )

    def sort_key(migration: Migration) -> tuple[int, str]:
        match = _NUMERIC_PREFIX.match(migration.id)
        return (int(match.group(1)) if match else 0, migration.id)

    return sorted(migrations, key=sort_key)


def find_pending(discovered: list[Migration], applied: dict[str, str]) -> list[Migration]:
    """Return migrations not yet applied, rejecting rewritten history.

    Raises:
        MigrationConflictError: an applied migration's checksum no longer
            matches the file, meaning the database cannot be reproduced from
            the repository.
    """
    pending: list[Migration] = []
    for migration in discovered:
        recorded = applied.get(migration.id)
        if recorded is None:
            pending.append(migration)
        elif recorded != migration.checksum:
            raise MigrationConflictError(
                f"{migration.id} was already applied but its contents changed "
                f"(recorded {recorded[:12]}, on disk {migration.checksum[:12]}). "
                "Applied migrations are immutable -- add a new one instead."
            )
    return pending


async def fetch_applied(graph: SupportsRead) -> dict[str, str]:
    return {row["id"]: row["checksum"] for row in await graph.read(APPLIED_MIGRATIONS_CYPHER)}


async def apply_migrations(
    graph: GraphClient, directory: Path = MIGRATIONS_DIR, *, dry_run: bool = False
) -> list[str]:
    """Apply every pending migration in order. Returns the ids applied."""
    pending = find_pending(discover_migrations(directory), await fetch_applied(graph))
    if not pending:
        log.info("no pending migrations")
        return []

    if dry_run:
        for migration in pending:
            log.info("pending: %s (%d statements)", migration.id, len(migration.statements))
        return []

    applied: list[str] = []
    for migration in pending:
        started = time.perf_counter()
        for statement in migration.statements:
            await graph.execute_schema(statement, timeout=60)
        duration_ms = int((time.perf_counter() - started) * 1000)
        await graph.write(
            RECORD_MIGRATION_CYPHER,
            {"id": migration.id, "checksum": migration.checksum, "duration_ms": duration_ms},
        )
        log.info("applied %s in %dms", migration.id, duration_ms)
        applied.append(migration.id)
    return applied


def _format_applied_at(value: object) -> str:
    """Render the applied_at column for --status.

    ``GraphClient`` already coerces the driver's native temporal to a Python
    ``datetime`` before this code sees it, so formatting is a plain isoformat
    call rather than anything CognoDB-specific.
    """
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    return str(value)


async def print_status(graph: GraphClient) -> None:
    rows = await graph.read(APPLIED_MIGRATIONS_CYPHER)
    pending = find_pending(
        discover_migrations(MIGRATIONS_DIR), {r["id"]: r["checksum"] for r in rows}
    )
    print(f"{'MIGRATION':<34} {'STATUS':<9} APPLIED AT")
    for row in rows:
        print(f"{row['id']:<34} {'applied':<9} {_format_applied_at(row['applied_at'])}")
    for migration in pending:
        print(f"{migration.id:<34} {'pending':<9} -")


async def main() -> int:
    parser = argparse.ArgumentParser(description="Apply graph migrations.")
    parser.add_argument("--dry-run", action="store_true", help="list pending, change nothing")
    parser.add_argument("--status", action="store_true", help="show applied and pending")
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings)
    async with GraphClient.connect(settings) as graph:
        try:
            if args.status:
                await print_status(graph)
            else:
                await apply_migrations(graph, dry_run=args.dry_run)
        except MigrationConflictError as exc:
            # Expected operator error, not a crash: an edited migration is a
            # designed refusal (and the caller's exit-code check on this
            # process is what stops `migrate && uvicorn` booting against a
            # diverged schema), so it gets a clean message, not a traceback.
            log.error(str(exc))
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
