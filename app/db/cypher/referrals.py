"""The two queries this application exists to answer.

VERIFIED AGAINST THE LIVE INSTANCE: CognoDB rejects a parameterised
variable-length bound -- `[:KNOWS*1..$max_hops]` is a syntax error
("expected ], got PARAM"). So each query carries a literal ceiling and the
caller's narrower request is applied as `WHERE length(path) <= $max_hops`.
One statement, one literal bound, full parameterised control, and no string
building anywhere.

The two queries do NOT share a literal ceiling, and that is deliberate --
measured against the live instance, against `Cadence Retail` (the worst-case,
4-hop-away company):

| Form                                          | Time     |
|------------------------------------------------|---------:|
| `*1..5` + `WHERE length(path) <= 4` (Q2)       | 5,411 ms |
| `*1..4` literal, same filter (Q2)              | 2,063 ms |

The traversal explores to the *literal* bound regardless of the `WHERE`
filter narrowing it afterwards, so a looser literal ceiling than the query
actually needs is pure wasted work. Q1 (introduction routes) targets one
person and runs once per request, so its literal ceiling can stay at the
application's full 5-hop maximum cheaply. Q2 (company insiders) runs
`shortestPath` once *per insider* -- up to several dozen per company -- so
its literal ceiling is pinned to its own default (4) instead of the global
maximum. A caller asking `find_company_insiders(..., max_hops=5)` still gets
a fast, correct answer up to hop 4; reaching a fifth-hop insider needs the
per-target `find_routes` query instead, which is the acceptable trade here.

Both rank by confidence, not by length: `reduce` multiplies tie strength
along the path in a single expression. In SQL, path-dependent aggregation
like this means either a procedural loop or materialising every candidate
path and scoring it afterwards.
"""

from __future__ import annotations

#: Q1 -- best introduction routes to one person.
#:
#: allShortestPaths, not shortestPath: we want every equally-short route so they
#: can be *ranked* against each other by confidence. shortestPath returns one
#: arbitrary path and would hide the strongest one.
#:
#: KNOWS is traversed undirected (-[:KNOWS]-) because acquaintance is symmetric,
#: while being stored as a single directed edge. Storing one edge instead of two
#: halves write volume and removes any chance of the two directions drifting
#: apart; the cost is that asymmetric familiarity cannot be modelled.
INTRODUCTION_ROUTES_CYPHER = """
MATCH path = allShortestPaths(
  (me:Person {id: $viewer_id})-[:KNOWS*1..5]-(target:Person {id: $target_id})
)
WHERE length(path) <= $max_hops
WITH path,
     reduce(score = 1.0, r IN relationships(path) | score * r.strength) AS confidence
RETURN [n IN nodes(path) | n.name]            AS chain,
       [r IN relationships(path) | r.context] AS contexts,
       [r IN relationships(path) | r.strength] AS strengths,
       length(path)                           AS hops,
       round(confidence * 1000) / 1000.0      AS confidence
ORDER BY confidence DESC, hops ASC
LIMIT $limit
"""

#: Q2 -- reach into a target company. The query the demo opens on.
#:
#: shortestPath here, not allShortestPaths: we want the single best way to reach
#: each insider, and there may be dozens of insiders. Enumerating every
#: equally-short path to every one of them would be enormously more work for an
#: answer the UI does not show.
#:
#: Literal ceiling is *1..4, not *1..5 -- see the module docstring. This query
#: runs shortestPath once per insider, so the wasted exploration from a looser
#: literal bound multiplies by however many people currently work there.
COMPANY_INSIDERS_CYPHER = """
MATCH (insider:Person)-[:WORKED_AT {current: true}]->(:Company {name: $company})
WHERE insider.id <> $viewer_id
MATCH path = shortestPath(
  (me:Person {id: $viewer_id})-[:KNOWS*1..4]-(insider)
)
WHERE length(path) <= $max_hops
WITH insider, path,
     reduce(score = 1.0, r IN relationships(path) | score * r.strength) AS confidence
RETURN insider.id    AS person_id,
       insider.name  AS name,
       insider.title AS title,
       [n IN nodes(path) | n.name]             AS chain,
       [r IN relationships(path) | r.context]  AS contexts,
       [r IN relationships(path) | r.strength] AS strengths,
       length(path)                            AS hops,
       round(confidence * 1000) / 1000.0       AS confidence
ORDER BY confidence DESC, hops ASC
LIMIT $limit
"""
