"""Cypher for reading and updating people."""

from __future__ import annotations

#: Q5 -- everything the profile screen needs in one round trip.
#:
#: Each OPTIONAL MATCH is collapsed with its own `WITH ... collect(DISTINCT
#: ...)` before the next one runs, rather than chaining all five bare and
#: aggregating once at the end. Without that boundary, the row count between
#: two OPTIONAL MATCHes is the *product* of each pattern's fan-out, not the
#: sum -- a person with E employments, S skills, PR projects and M mutual
#: connections produces on the order of E*S*PR*M intermediate rows before
#: `collect(DISTINCT)` ever runs, which fixes correctness but not cost, and
#: that product grows without bound as the seeded network grows even though
#: no single field ever does.
#:
#: Measured live, worst case on the current 500-person snapshot (`me`, the
#: richest-seeded node -- 2 employments, 5 skills, 1 project, KNOWS-degree
#: 20; also the highest KNOWS-degree person in the graph, p0332, tried as
#: their own self-view): both the unchained and chained forms land at
#: 520-535 ms, statistically indistinguishable from the ~500 ms network
#: round trip that dominates every query here. At today's fan-out (products
#: in the low hundreds of rows at most) chaining is not a measured win; it is
#: cheap insurance against a query whose cost is currently invisible only
#: because no seeded person has enough edges to make the product large. A
#: person with, say, 10 employments and 30 skills would multiply to 300 rows
#: before the first `collect(DISTINCT)` under the old form -- still not
#: enormous on its own, but only one axis away from actually mattering.
#:
#: OPTIONAL MATCH itself is still load-bearing throughout: a person with no
#: projects must still render a profile rather than vanish from the result
#: set. It is the graph equivalent of a LEFT JOIN.
PERSON_PROFILE_CYPHER = """
MATCH (p:Person {id: $person_id})
OPTIONAL MATCH (p)-[w:WORKED_AT]->(c:Company)
WITH p, collect(DISTINCT {company: c.name, from_year: w.from,
                          to_year: w.to, is_current: coalesce(w.current, false)}) AS employment
OPTIONAL MATCH (p)-[:HAS_SKILL]->(s:Skill)
WITH p, employment, collect(DISTINCT s.name) AS skills
OPTIONAL MATCH (p)-[:WORKS_ON]->(pr:Project)
WITH p, employment, skills, collect(DISTINCT pr.name) AS projects
OPTIONAL MATCH (p)-[:MEMBER_OF]->(t:Team)
WITH p, employment, skills, projects, head(collect(DISTINCT t.name)) AS team
OPTIONAL MATCH (viewer:Person {id: $viewer_id})-[:KNOWS]-(mutual:Person)-[:KNOWS]-(p)
RETURN p.id        AS id,
       p.name      AS name,
       p.title     AS title,
       p.seniority AS seniority,
       coalesce(p.headline, '') AS headline,
       employment,
       skills,
       projects,
       team,
       collect(DISTINCT mutual.name) AS mutual_connections
"""

#: Same query, for the one viewer who can never have a meaningful "mutual
#: connections with themselves": looking at your own profile. Dropping the
#: match entirely -- rather than running it and discarding the result -- is
#: not just cheaper (this path is also what `update_profile` pays on every
#: single PATCH, since it re-reads via this exact self-view); it is also
#: correct. `(viewer:Person {id: $person_id})-[:KNOWS]-(mutual)-[:KNOWS]-(p)`
#: with viewer == p degenerates into "people who know me", which the API
#: would then hand back labelled as *your* mutual connections with
#: *yourself* -- a meaningless answer to a question nobody asked.
PERSON_SELF_PROFILE_CYPHER = """
MATCH (p:Person {id: $person_id})
OPTIONAL MATCH (p)-[w:WORKED_AT]->(c:Company)
WITH p, collect(DISTINCT {company: c.name, from_year: w.from,
                          to_year: w.to, is_current: coalesce(w.current, false)}) AS employment
OPTIONAL MATCH (p)-[:HAS_SKILL]->(s:Skill)
WITH p, employment, collect(DISTINCT s.name) AS skills
OPTIONAL MATCH (p)-[:WORKS_ON]->(pr:Project)
WITH p, employment, skills, collect(DISTINCT pr.name) AS projects
OPTIONAL MATCH (p)-[:MEMBER_OF]->(t:Team)
WITH p, employment, skills, projects, head(collect(DISTINCT t.name)) AS team
RETURN p.id        AS id,
       p.name      AS name,
       p.title     AS title,
       p.seniority AS seniority,
       coalesce(p.headline, '') AS headline,
       employment,
       skills,
       projects,
       team,
       [] AS mutual_connections
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
