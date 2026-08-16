"""Cypher for reading and updating people."""

from __future__ import annotations

#: Q5 -- everything the profile screen needs in one round trip.
#:
#: OPTIONAL MATCH throughout is load-bearing: a person with no projects must
#: still render a profile rather than vanish from the result set. It is the
#: graph equivalent of a LEFT JOIN.
PERSON_PROFILE_CYPHER = """
MATCH (p:Person {id: $person_id})
OPTIONAL MATCH (p)-[w:WORKED_AT]->(c:Company)
OPTIONAL MATCH (p)-[:HAS_SKILL]->(s:Skill)
OPTIONAL MATCH (p)-[:WORKS_ON]->(pr:Project)
OPTIONAL MATCH (p)-[:MEMBER_OF]->(t:Team)
OPTIONAL MATCH (viewer:Person {id: $viewer_id})-[:KNOWS]-(mutual:Person)-[:KNOWS]-(p)
RETURN p.id        AS id,
       p.name      AS name,
       p.title     AS title,
       p.seniority AS seniority,
       coalesce(p.headline, '') AS headline,
       collect(DISTINCT {company: c.name, from_year: w.from,
                         to_year: w.to, is_current: coalesce(w.current, false)}) AS employment,
       collect(DISTINCT s.name)      AS skills,
       collect(DISTINCT pr.name)     AS projects,
       head(collect(DISTINCT t.name)) AS team,
       collect(DISTINCT mutual.name) AS mutual_connections
"""

#: Updates are a whitelisted property map, never an interpolated SET clause.
#: `p += $changes` merges only the supplied keys, which is exactly PATCH
#: semantics and cannot be coerced into writing a property the API did not
#: expose.
UPDATE_PERSON_CYPHER = """
MATCH (p:Person {id: $person_id})
SET p += $changes
RETURN p.id AS id
"""
