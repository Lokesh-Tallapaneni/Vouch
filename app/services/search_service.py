"""Typeahead search."""

from __future__ import annotations

from app.db.client import GraphClient
from app.db.cypher.search import SEARCH_COMPANIES_CYPHER, SEARCH_PEOPLE_CYPHER
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
        return [PersonSummary.model_validate(row) for row in rows]

    async def search_companies(self, term: str, limit: int = 8) -> list[str]:
        normalised = self._normalise(term)
        if normalised is None:
            return []
        rows = await self._graph.read(
            SEARCH_COMPANIES_CYPHER, {"term": normalised, "limit": self._clamp(limit)}
        )
        return [str(row["name"]) for row in rows]

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
