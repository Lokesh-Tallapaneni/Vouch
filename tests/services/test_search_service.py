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


async def test_search_people_deduplicates_by_person_id() -> None:
    # Regression: an inline relationship property on an OPTIONAL MATCH
    # (`[:WORKED_AT {current: true}]`) is silently ignored on CognoDB, so
    # SEARCH_PEOPLE_CYPHER used to return one row per employment rather than
    # one per person -- fixed in the Cypher itself (a WHERE clause bound to
    # the relationship variable instead), but FakeGraph cannot reproduce a
    # server-side duplication, so this pins the service-layer contract
    # directly: given two rows for the same person, only one comes back,
    # regardless of what the query underneath does.
    duplicate_rows = [
        {**PERSON_ROW, "current_company": "Everline"},
        {**PERSON_ROW, "current_company": "Halcyon Media"},
    ]
    graph = FakeGraph({_PEOPLE_FRAGMENT: duplicate_rows})
    results = await SearchService(graph).search_people("pri")
    assert len(results) == 1
    assert results[0].id == "p0001"


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


_LIST_FRAGMENT = "count(p) AS headcount"
_SUGGEST_FRAGMENT = "count(DISTINCT insider) AS near"


async def test_listing_companies_does_not_go_through_the_prefix_search() -> None:
    # A bare GET /companies used to return [] because it called
    # search_companies with an empty term, which correctly refuses to query.
    # Listing is a different question from searching and runs its own
    # statement -- asserting on the cypher, not just the result, is what
    # stops it being quietly rewired back to the prefix search.
    graph = FakeGraph({_LIST_FRAGMENT: [{"name": "Everline", "headcount": 54}]})
    assert await SearchService(graph).list_companies() == ["Everline"]
    assert _COMPANIES_FRAGMENT not in graph.calls[0].cypher


async def test_suggestions_rank_by_the_viewers_own_connections() -> None:
    # The landing page's chips are per viewer, not a fixed list: whoever the
    # viewer knows most people near comes first.
    graph = FakeGraph(
        {
            _SUGGEST_FRAGMENT: [
                {"name": "Halcyon Media", "near": 23},
                {"name": "Aeromark", "near": 15},
            ]
        }
    )
    assert await SearchService(graph).suggest_companies("me", limit=2) == [
        "Halcyon Media",
        "Aeromark",
    ]


async def test_a_viewer_with_no_connections_still_gets_suggestions() -> None:
    # A brand-new account knows nobody, so the two-hop query returns nothing.
    # An empty landing page is worse than one offering somewhere plausible,
    # so it tops up from the plain company list.
    graph = FakeGraph(
        {
            _SUGGEST_FRAGMENT: [],
            _LIST_FRAGMENT: [
                {"name": "Bluecrest Labs", "headcount": 69},
                {"name": "Greenfield Health", "headcount": 67},
            ],
        }
    )
    assert await SearchService(graph).suggest_companies("nobody", limit=2) == [
        "Bluecrest Labs",
        "Greenfield Health",
    ]


async def test_topping_up_suggestions_cannot_duplicate_a_company() -> None:
    # The top-up list overlaps the suggestions by construction -- both are
    # drawn from the same companies -- so a naive concatenation would show
    # the same chip twice.
    graph = FakeGraph(
        {
            _SUGGEST_FRAGMENT: [{"name": "Halcyon Media", "near": 23}],
            _LIST_FRAGMENT: [
                {"name": "Halcyon Media", "headcount": 65},
                {"name": "Bluecrest Labs", "headcount": 69},
            ],
        }
    )
    assert await SearchService(graph).suggest_companies("me", limit=2) == [
        "Halcyon Media",
        "Bluecrest Labs",
    ]
