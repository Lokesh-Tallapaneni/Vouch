from __future__ import annotations

from scripts.generate import build_network
from scripts.load import batched, load_snapshot
from tests.support.fake_graph import FakeGraph


def test_batched_splits_into_full_and_partial_chunks() -> None:
    assert batched(list(range(5)), 2) == [[0, 1], [2, 3], [4]]


def test_batched_returns_nothing_for_an_empty_sequence() -> None:
    assert batched([], 10) == []


async def test_loading_sends_every_statement_with_parameters_only() -> None:
    graph = FakeGraph()
    await load_snapshot(graph, build_network(), batch_size=500)
    assert graph.calls, "loader issued no queries"
    for call in graph.calls:
        assert "$" in call.cypher, "a statement was built without parameters"
        assert call.params, "a statement was sent with no parameters"


async def test_loading_batches_rather_than_sending_one_row_per_round_trip() -> None:
    graph = FakeGraph()
    snapshot = build_network()
    await load_snapshot(graph, snapshot, batch_size=500)
    # One round trip per row over Bolt on a burstable instance is unusably slow.
    assert len(graph.calls) < len(snapshot.acquaintances) / 10


async def test_loading_is_idempotent_every_statement_is_merge_shaped() -> None:
    # MERGE throughout means a second load updates rather than duplicates.
    # A stray CREATE would double every node and relationship on re-run.
    graph = FakeGraph()
    snapshot = build_network()
    await load_snapshot(graph, snapshot, batch_size=500)
    await load_snapshot(graph, snapshot, batch_size=500)
    for call in graph.calls:
        assert "MERGE" in call.cypher, f"non-idempotent statement issued: {call.cypher!r}"
        assert "CREATE" not in call.cypher
