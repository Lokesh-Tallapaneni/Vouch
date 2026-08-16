from __future__ import annotations

from app.services.search_service import MIN_SEARCH_LENGTH, SearchService
from tests.support.fake_graph import FakeGraph

ROW = {
    "id": "p0001",
    "name": "Priya Sharma",
    "title": "Staff Engineer",
    "current_company": "Everline",
}


async def test_search_returns_person_summaries() -> None:
    results = await SearchService(FakeGraph({"STARTS WITH": [ROW]})).search_people("pri")
    assert results[0].name == "Priya Sharma" and results[0].current_company == "Everline"


async def test_a_term_shorter_than_the_minimum_queries_nothing() -> None:
    # Every keystroke firing a query against a burstable instance is how you
    # make a demo feel broken.
    graph = FakeGraph({"STARTS WITH": [ROW]})
    assert await SearchService(graph).search_people("p") == []
    assert graph.calls == []


async def test_a_blank_term_queries_nothing() -> None:
    graph = FakeGraph({"STARTS WITH": [ROW]})
    assert await SearchService(graph).search_people("   ") == []
    assert graph.calls == []


async def test_the_term_is_lowercased_and_passed_as_a_parameter() -> None:
    graph = FakeGraph({"STARTS WITH": [ROW]})
    await SearchService(graph).search_people("  PRI  ")
    assert graph.calls[0].params["term"] == "pri"


async def test_the_limit_is_clamped_to_a_sane_maximum() -> None:
    graph = FakeGraph({"STARTS WITH": [ROW]})
    await SearchService(graph).search_people("pri", limit=10_000)
    assert graph.calls[0].params["limit"] <= 50


def test_the_minimum_search_length_is_two() -> None:
    assert MIN_SEARCH_LENGTH == 2
