"""Network-health analytics."""

from __future__ import annotations

from app.db.client import GraphClient
from app.db.cypher.network import BROKERS_CYPHER, BUS_FACTOR_CYPHER
from app.models.network import Broker, BusFactorRisk

MAX_RESULTS = 100


class NetworkService:
    def __init__(self, graph: GraphClient) -> None:
        self._graph = graph

    async def find_brokers(self, limit: int = 15) -> list[Broker]:
        rows = await self._graph.read(BROKERS_CYPHER, {"limit": self._clamp(limit)}, timeout=20)
        return [Broker.model_validate(row) for row in rows]

    async def find_bus_factor_risks(self, limit: int = 25) -> list[BusFactorRisk]:
        rows = await self._graph.read(BUS_FACTOR_CYPHER, {"limit": self._clamp(limit)}, timeout=20)
        return [BusFactorRisk.model_validate(row) for row in rows]

    @staticmethod
    def _clamp(limit: int) -> int:
        return max(1, min(limit, MAX_RESULTS))
