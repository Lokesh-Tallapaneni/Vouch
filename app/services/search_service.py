"""Typeahead search."""

from __future__ import annotations

from collections.abc import Iterable

from app.db.client import GraphClient
from app.db.cypher.search import (
    LIST_COMPANIES_CYPHER,
    SEARCH_COMPANIES_CYPHER,
    SEARCH_PEOPLE_CYPHER,
    SUGGEST_COMPANIES_CYPHER,
)
from app.models.person import PersonSummary

#: Below this, a prefix match is nearly the whole dataset and the query is
#: both slow and useless.
MIN_SEARCH_LENGTH = 2

#: Hard ceiling regardless of what the caller asks for. A typeahead needs a
#: handful of rows; anything larger is either a mistake or an attempt to dump
#: the dataset one request at a time.
MAX_SEARCH_RESULTS = 50


class SearchService:
    def __init__(self, graph: GraphClient) -> None:
        self._graph = graph

    async def search_people(self, term: str, limit: int = 8) -> list[PersonSummary]:
        normalised = self._normalise(term)
        if normalised is None:
            return []
        rows = await self._graph.read(
            SEARCH_PEOPLE_CYPHER, {"term": normalised, "limit": self._clamp(limit)}
        )
        return self._dedupe_by_id(PersonSummary.model_validate(row) for row in rows)

    @staticmethod
    def _dedupe_by_id(summaries: Iterable[PersonSummary]) -> list[PersonSummary]:
        """Keep the first occurrence of each person id.

        Defense in depth, not a workaround left in after the real fix: a
        CognoDB divergence (an inline relationship property on an OPTIONAL
        MATCH is silently ignored) previously made SEARCH_PEOPLE_CYPHER
        return one row per employment rather than one per person. Fixed at
        the query, but this pins the service's own contract -- one row per
        person -- regardless of what the query underneath does or how the
        engine behaves.
        """
        seen: set[str] = set()
        deduped: list[PersonSummary] = []
        for summary in summaries:
            if summary.id in seen:
                continue
            seen.add(summary.id)
            deduped.append(summary)
        return deduped

    async def search_companies(self, term: str, limit: int = 8) -> list[str]:
        normalised = self._normalise(term)
        if normalised is None:
            return []
        rows = await self._graph.read(
            SEARCH_COMPANIES_CYPHER, {"term": normalised, "limit": self._clamp(limit)}
        )
        return [str(row["name"]) for row in rows]

    async def list_companies(self, limit: int = 8) -> list[str]:
        """The companies with the most current employees, busiest first.

        Distinct from ``search_companies``: that one answers "what starts with
        the letters someone typed" and correctly returns nothing for an empty
        term, since a typeahead should not query on every keystroke. This one
        answers "what is in here at all", which is what a bare
        ``GET /companies`` and the landing page's suggestion chips need.
        """
        rows = await self._graph.read(LIST_COMPANIES_CYPHER, {"limit": self._clamp(limit)})
        return [str(row["name"]) for row in rows]

    async def suggest_companies(self, viewer_id: str, limit: int = 4) -> list[str]:
        """Where this viewer should start: companies they have the most
        connections into within two hops.

        Tops up from ``list_companies`` when the viewer has few or no close
        connections -- a brand-new account has none at all, and a landing
        page whose suggestions are empty is worse than one suggesting
        somewhere merely plausible. The top-up preserves ranking order and
        cannot introduce duplicates.
        """
        capped = self._clamp(limit)
        rows = await self._graph.read(
            SUGGEST_COMPANIES_CYPHER, {"viewer_id": viewer_id, "limit": capped}
        )
        names = [str(row["name"]) for row in rows]
        if len(names) >= capped:
            return names

        seen = set(names)
        for name in await self.list_companies(limit=capped):
            if len(names) >= capped:
                break
            if name not in seen:
                names.append(name)
                seen.add(name)
        return names

    @staticmethod
    def _normalise(term: str) -> str | None:
        """Lowercase and trim, or None if the term is too short to be worth a
        round trip. Returning early here is what stops every keystroke hitting
        the database."""
        cleaned = term.strip().lower()
        return cleaned if len(cleaned) >= MIN_SEARCH_LENGTH else None

    @staticmethod
    def _clamp(limit: int) -> int:
        return max(1, min(limit, MAX_SEARCH_RESULTS))
