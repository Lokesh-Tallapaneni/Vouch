"""Cypher for the typeahead.

Prefix search over the `person_name` range index from migration 0002.
Substring search would need a full-text index -- a deliberate scope line, and
worth stating in the README rather than leaving as an apparent oversight.

VERIFIED AGAINST THE LIVE INSTANCE: an inline relationship property on an
`OPTIONAL MATCH` is silently ignored on CognoDB -- `OPTIONAL MATCH
(p)-[:WORKED_AT {current: true}]->(c:Company)` returns *every* `WORKED_AT`
edge, not just the current one, so anyone with a previous employer appeared
twice in results (once per employment, the second row showing a stale
company). A plain `MATCH` with the same inline property filters correctly;
only `OPTIONAL MATCH` is affected. The fix is to bind the relationship and
filter it in a `WHERE` attached to the `OPTIONAL MATCH` instead of inline --
confirmed that returns exactly one row per person. Do not "simplify" this
back to the inline form; it silently reintroduces duplicate rows.
"""

from __future__ import annotations

SEARCH_PEOPLE_CYPHER = """
MATCH (p:Person)
WHERE toLower(p.name) STARTS WITH $term
OPTIONAL MATCH (p)-[w:WORKED_AT]->(c:Company)
  WHERE w.current = true
RETURN p.id AS id, p.name AS name, p.title AS title, c.name AS current_company
ORDER BY p.name
LIMIT $limit
"""

SEARCH_COMPANIES_CYPHER = """
MATCH (c:Company)
WHERE toLower(c.name) STARTS WITH $term
RETURN c.name AS name
ORDER BY c.name
LIMIT $limit
"""

#: Companies with the most current employees first.
#:
#: This exists because the landing page used to offer four company names
#: written directly into `app/web/pages.py` as a Python list. That is a
#: hardcoded answer to a question the graph can answer: rename a company,
#: reload the dataset, or point the app at a different instance and those
#: links 404 while still looking authoritative. Ranking by headcount also
#: puts the companies with the most reachable people first, which is what
#: someone clicking a suggestion actually wants.
#:
#: `count(p)` over the current-employment edge, not `size((c)<--())` -- the
#: latter counts every relationship into the company regardless of type or
#: currency. Inline `{current: true}` is safe on a plain MATCH; see this
#: module's docstring for why it would not be on an OPTIONAL MATCH.
LIST_COMPANIES_CYPHER = """
MATCH (p:Person)-[:WORKED_AT {current: true}]->(c:Company)
RETURN c.name AS name, count(p) AS headcount
ORDER BY headcount DESC, c.name
LIMIT $limit
"""

#: Companies where *this viewer* has the most connections within two hops.
#:
#: The landing page's suggestion chips answer "where should I start?", and
#: headcount answers a different question -- the biggest employer may be one
#: the viewer cannot reach well. Measured on the seeded graph: this ordering
#: puts Halcyon Media (23 close connections, best route 0.88) and Aeromark
#: (15, 0.81) first, which are in fact the two strongest ways in, while
#: headcount would lead with Bluecrest Labs, whose best route is 0.37.
#:
#: Deliberately a *proxy* rather than the real thing. Ranking by actual best
#: route confidence means a `shortestPath` from the viewer to every current
#: employee of every company; that query exceeds the free tier's statement
#: deadline outright (`Neo.TransientError.General.OutOfTimeError` on a 0.5
#: vCPU c0). A bounded two-hop expansion costs one round trip -- measured
#: 524 ms, the network floor -- and, as the numbers above show, ranks the
#: same way. Revisit on a larger instance.
#:
#: Companies the viewer has no two-hop path into are absent, not zero-valued;
#: callers wanting every company want LIST_COMPANIES_CYPHER instead.
SUGGEST_COMPANIES_CYPHER = """
MATCH (me:Person {id: $viewer_id})-[:KNOWS*1..2]-(insider:Person)
WHERE insider.id <> $viewer_id
MATCH (insider)-[:WORKED_AT {current: true}]->(c:Company)
RETURN c.name AS name, count(DISTINCT insider) AS near
ORDER BY near DESC, c.name
LIMIT $limit
"""
