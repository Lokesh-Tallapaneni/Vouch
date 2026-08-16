from __future__ import annotations

import pytest

from tests.support.fake_graph import AmbiguousFragmentError, FakeGraph


@pytest.mark.asyncio
async def test_returns_rows_matching_a_cypher_fragment() -> None:
    graph = FakeGraph({"MATCH (p:Person)": [{"id": "me"}]})
    assert await graph.read("MATCH (p:Person) RETURN p.id AS id") == [{"id": "me"}]


@pytest.mark.asyncio
async def test_returns_no_rows_when_nothing_matches() -> None:
    assert await FakeGraph({}).read("MATCH (x:Nothing) RETURN x") == []


@pytest.mark.asyncio
async def test_records_the_cypher_and_parameters_it_was_given() -> None:
    graph = FakeGraph({"RETURN": [{"ok": 1}]})
    await graph.read("RETURN $value AS ok", {"value": 1})
    assert graph.calls[0].params == {"value": 1}
    assert "RETURN" in graph.calls[0].cypher


@pytest.mark.asyncio
async def test_check_reports_ready_without_touching_a_socket() -> None:
    # Mirrors GraphClient.check()'s (ok, detail) shape so a fake app boot
    # exercising /ready never has to special-case which graph it got.
    assert await FakeGraph().check() == (True, "ok")


@pytest.mark.asyncio
async def test_execute_schema_records_the_statement_as_a_write() -> None:
    graph = FakeGraph()
    await graph.execute_schema("CREATE CONSTRAINT person_id IF NOT EXISTS ...")
    assert graph.calls[0].write is True
    assert "CREATE CONSTRAINT" in graph.calls[0].cypher


@pytest.mark.asyncio
async def test_a_query_matching_only_one_of_several_registered_fragments_resolves() -> None:
    # Registering more than one fragment is fine as long as a given query
    # only ever matches one of them -- the hazard is overlap, not plurality.
    graph = FakeGraph({"MATCH (p:Person)": [{"id": "me"}], "MATCH (c:Company)": [{"id": "acme"}]})
    assert await graph.read("MATCH (p:Person) RETURN p.id AS id") == [{"id": "me"}]


@pytest.mark.asyncio
async def test_a_query_matching_two_registered_fragments_raises() -> None:
    graph = FakeGraph({"MATCH (p:Person)": [{"id": "me"}], "RETURN p.id": [{"id": "someone-else"}]})
    with pytest.raises(AmbiguousFragmentError) as exc_info:
        await graph.read("MATCH (p:Person) RETURN p.id AS id")
    message = str(exc_info.value)
    assert "MATCH (p:Person)" in message
    assert "RETURN p.id" in message
