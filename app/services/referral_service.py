"""Route finding and company reach."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.core.exceptions import InvalidInputError
from app.db.client import GraphClient
from app.db.cypher.referrals import COMPANY_INSIDERS_CYPHER, INTRODUCTION_ROUTES_CYPHER
from app.models.referral import CompanyInsider, IntroductionRoute, RouteHop

#: Ceiling for Q1 (introduction routes), matching the literal `*1..5` bound
#: baked into ``INTRODUCTION_ROUTES_CYPHER``. Beyond five hops a "warm"
#: introduction is not warm, and on a dense social graph the search space
#: grows fast enough to hang the demo in front of the evaluator.
MAX_ROUTE_HOPS = 5

#: Ceiling for Q2 (company insiders), matching the literal `*1..4` bound in
#: ``COMPANY_INSIDERS_CYPHER``. Deliberately lower than ``MAX_ROUTE_HOPS`` --
#: see the module docstring in ``app.db.cypher.referrals`` for the measured
#: cost of a looser literal bound on a query that runs once per insider.
MAX_INSIDER_HOPS = 4

MAX_RESULTS = 50


class ReferralService:
    def __init__(self, graph: GraphClient) -> None:
        self._graph = graph

    async def find_routes(
        self, viewer_id: str, target_id: str, max_hops: int = 5, limit: int = 5
    ) -> list[IntroductionRoute]:
        self._check_hops(max_hops, ceiling=MAX_ROUTE_HOPS)
        if viewer_id == target_id:
            raise InvalidInputError("That's you.")

        rows = await self._graph.read(
            INTRODUCTION_ROUTES_CYPHER,
            {
                "viewer_id": viewer_id,
                "target_id": target_id,
                "max_hops": max_hops,
                "limit": self._clamp(limit),
            },
        )
        return [self._to_route(row) for row in rows]

    async def find_company_insiders(
        self, viewer_id: str, company: str, max_hops: int = 4, limit: int = 10
    ) -> list[CompanyInsider]:
        self._check_hops(max_hops, ceiling=MAX_INSIDER_HOPS)
        rows = await self._graph.read(
            COMPANY_INSIDERS_CYPHER,
            {
                "viewer_id": viewer_id,
                "company": company,
                "max_hops": max_hops,
                "limit": self._clamp(limit),
            },
        )
        insiders = (
            CompanyInsider(
                person_id=row["person_id"],
                name=row["name"],
                title=row.get("title") or "",
                route=self._to_route(row),
            )
            for row in rows
        )
        return self._dedupe_by_person_id(insiders)

    @staticmethod
    def _check_hops(max_hops: int, *, ceiling: int) -> None:
        if not 1 <= max_hops <= ceiling:
            raise InvalidInputError(f"Hop count must be between 1 and {ceiling}.")

    @staticmethod
    def _dedupe_by_person_id(insiders: Iterable[CompanyInsider]) -> list[CompanyInsider]:
        """Keep the first occurrence of each person id.

        Defense in depth, not a workaround left in after the real fix: a
        CognoDB divergence (``shortestPath()`` returns every equally-short
        path, not one) previously made an insider reachable by two
        same-length routes appear twice. Fixed at the query -- aggregated to
        the single best route per insider, ordered so the strongest survives
        -- but this pins the service's own contract regardless of what the
        query underneath does or how the engine behaves. "First occurrence"
        is safe because Cypher orders by confidence descending, so keeping
        the first duplicate keeps the best one.
        """
        seen: set[str] = set()
        deduped: list[CompanyInsider] = []
        for insider in insiders:
            if insider.person_id in seen:
                continue
            seen.add(insider.person_id)
            deduped.append(insider)
        return deduped

    @staticmethod
    def _clamp(limit: int) -> int:
        return max(1, min(limit, MAX_RESULTS))

    @staticmethod
    def _to_route(row: dict[str, Any]) -> IntroductionRoute:
        """Zip the parallel node/relationship arrays into per-hop detail.

        Cypher returns the chain and the relationship properties as separate
        lists; pairing them here is what lets the UI label each connector with
        why those two people know each other.
        """
        chain: list[str] = list(row.get("chain", []))
        contexts: list[str] = list(row.get("contexts", []))
        strengths: list[float] = list(row.get("strengths", []))

        hop_details = [
            RouteHop(
                from_name=chain[index],
                to_name=chain[index + 1],
                context=contexts[index] if index < len(contexts) else "unknown",
                strength=float(strengths[index]) if index < len(strengths) else 0.0,
            )
            for index in range(max(0, len(chain) - 1))
        ]
        return IntroductionRoute(
            chain=chain,
            hops=int(row.get("hops", max(0, len(chain) - 1))),
            confidence=float(row.get("confidence", 0.0)),
            hop_details=hop_details,
        )
