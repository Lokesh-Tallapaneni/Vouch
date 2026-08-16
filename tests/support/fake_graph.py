"""A GraphClient stand-in for unit tests.

Service tests exist to prove that result rows become the right domain models
and that the right parameters were sent. Neither needs a database, and a unit
suite that opens sockets is a unit suite that fails on a train.

Rows are keyed by a distinctive fragment of the query rather than by the whole
string, so reformatting Cypher does not break unrelated tests.

Covers the whole surface of ``app.db.client.GraphClient`` that the app
actually calls, not just ``read``/``write``: ``/ready`` calls ``.check()``,
and the migration runner calls ``.execute_schema()``. A double whose surface
stops short of that would let a test pass right up until it hit the missing
method -- with an ``AttributeError``, not the assertion it was written to
check.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class RecordedCall:
    cypher: str
    params: dict[str, Any]
    write: bool


@dataclass
class FakeGraph:
    rows_by_fragment: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    calls: list[RecordedCall] = field(default_factory=list)

    async def read(
        self,
        cypher: str,
        params: Mapping[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> list[dict[str, Any]]:
        return self._respond(cypher, params, write=False)

    async def write(
        self,
        cypher: str,
        params: Mapping[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> list[dict[str, Any]]:
        return self._respond(cypher, params, write=True)

    async def check(self) -> tuple[bool, str]:
        """Always ready. A test that wants a downed graph subclasses and overrides."""
        return True, "ok"

    async def execute_schema(self, statement: str, *, timeout: float | None = None) -> None:
        """Record the statement; there is no schema to change in a fake."""
        self.calls.append(RecordedCall(statement, {}, write=True))

    def _respond(
        self, cypher: str, params: Mapping[str, Any] | None, *, write: bool
    ) -> list[dict[str, Any]]:
        self.calls.append(RecordedCall(cypher, dict(params or {}), write))
        for fragment, rows in self.rows_by_fragment.items():
            if fragment in cypher:
                return rows
        return []
