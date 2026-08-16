"""Cypher for the typeahead.

Prefix search over the `person_name` range index from migration 0002.
Substring search would need a full-text index -- a deliberate scope line, and
worth stating in the README rather than leaving as an apparent oversight.
"""

from __future__ import annotations

SEARCH_PEOPLE_CYPHER = """
MATCH (p:Person)
WHERE toLower(p.name) STARTS WITH $term
OPTIONAL MATCH (p)-[:WORKED_AT {current: true}]->(c:Company)
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
