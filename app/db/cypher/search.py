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
