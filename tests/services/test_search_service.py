from __future__ import annotations

from app.services.search_service import MIN_SEARCH_LENGTH, SearchService
from tests.support.fake_graph import FakeGraph

PERSON_ROW = {
    "id": "p0001",
    "name": "Priya Sharma",
    "title": "Staff Engineer",
    "current_company": "Everline",
}

COMPANY_ROW = {"name": "Everline"}

#: Fragments unique to one statement each. "STARTS WITH" alone matches both
#: SEARCH_PEOPLE_CYPHER and SEARCH_COMPANIES_CYPHER (they share that clause
#: verbatim, just on different variables) -- registering only that would let
#: search_people run the companies query, or vice versa, and every test below
#: would still pass. Naming the variable disambiguates, and every test that
#: uses these also asserts on `call.cypher` directly rather than trusting the
#: fragment match alone to prove the right query ran.
_PEOPLE_FRAGMENT = "toLower(p.name) STARTS WITH"
_COMPANIES_FRAGMENT = "toLower(c.name) STARTS WITH"


async def test_search_returns_person_summaries() -> None:
    graph = FakeGraph({_PEOPLE_FRAGMENT: [PERSON_ROW]})
    results = await SearchService(graph).search_people("pri")
    assert results[0].name == "Priya Sharma" and results[0].current_company == "Everline"
    assert _PEOPLE_FRAGMENT in graph.calls[0].cypher
    assert _COMPANIES_FRAGMENT not in graph.calls[0].cypher


async def test_search_companies_returns_bare_names() -> None:
    # Distinct from search_people at every layer: a different Cypher
    # statement, a different row shape (no id/title), and a bare list[str]
    # return type rather than a list of PersonSummary. If search_companies
    # were ever wired to SEARCH_PEOPLE_CYPHER by mistake, this is the test
    # that would catch it -- both the cypher assertion and the result shape.
    graph = FakeGraph({_COMPANIES_FRAGMENT: [COMPANY_ROW]})
    results = await SearchService(graph).search_companies("ev")
    assert results == ["Everline"]
    assert _COMPANIES_FRAGMENT in graph.calls[0].cypher
    assert _PEOPLE_FRAGMENT not in graph.calls[0].cypher


async def test_a_term_shorter_than_the_minimum_queries_nothing() -> None:
    # Every keystroke firing a query against a burstable instance is how you
    # make a demo feel broken.
    graph = FakeGraph({_PEOPLE_FRAGMENT: [PERSON_ROW]})
    assert await SearchService(graph).search_people("p") == []
    assert graph.calls == []


async def test_a_blank_term_queries_nothing() -> None:
    graph = FakeGraph({_PEOPLE_FRAGMENT: [PERSON_ROW]})
    assert await SearchService(graph).search_people("   ") == []
    assert graph.calls == []


async def test_companies_search_below_the_minimum_also_queries_nothing() -> None:
    graph = FakeGraph({_COMPANIES_FRAGMENT: [COMPANY_ROW]})
    assert await SearchService(graph).search_companies("e") == []
    assert graph.calls == []


async def test_the_term_is_lowercased_and_passed_as_a_parameter() -> None:
    graph = FakeGraph({_PEOPLE_FRAGMENT: [PERSON_ROW]})
    await SearchService(graph).search_people("  PRI  ")
    assert graph.calls[0].params["term"] == "pri"


async def test_the_limit_is_clamped_to_a_sane_maximum() -> None:
    graph = FakeGraph({_PEOPLE_FRAGMENT: [PERSON_ROW]})
    await SearchService(graph).search_people("pri", limit=10_000)
    assert graph.calls[0].params["limit"] <= 50


async def test_the_companies_limit_is_also_clamped_to_a_sane_maximum() -> None:
    graph = FakeGraph({_COMPANIES_FRAGMENT: [COMPANY_ROW]})
    await SearchService(graph).search_companies("ev", limit=10_000)
    assert graph.calls[0].params["limit"] <= 50


def test_the_minimum_search_length_is_two() -> None:
    assert MIN_SEARCH_LENGTH == 2
