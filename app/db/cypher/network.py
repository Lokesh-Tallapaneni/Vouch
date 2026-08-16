"""Network-health queries.

Q3 is the exhibit for "a query a relational database would find awkward": a
three-node match that excludes pairs which are directly connected. In SQL that
is a NOT EXISTS correlated subquery over a double self-join, and near-unreadable
at that.

MEASURED AGAINST THE LIVE INSTANCE -- two things differ from textbook Cypher:

1. **Pattern predicates in WHERE do not work on CognoDB.** `NOT (a)-[:KNOWS]-(c)`,
   `NOT EXISTS { MATCH (a)-[:KNOWS]-(c) }` and `NOT exists((a)-[:KNOWS]-(c))` all
   evaluate as though the pattern were always present: the positive forms return
   every row and the negations return zero. Verified against ground truth
   computed independently from the snapshot (30,383 candidate neighbour pairs,
   9,257 genuinely not directly connected). The **pattern comprehension**
   `size([(a)-[:KNOWS]-(c) | 1]) = 0` is correct -- it returns exactly 9,257 of
   30,383 pairs, matching the Python computation exactly.

2. **Anchor the match on the broker.** The original form matched
   `(a:Person)-[:MEMBER_OF]->(ta)` and `(c:Person)-[:MEMBER_OF]->(tc)` as two
   free matches before relating them, which builds a 500x500 product before any
   filter and times out at 30s. Starting from the two-hop path and looking up
   teams per endpoint runs in ~3.5s.

`elementId(a) < elementId(c)` deduplicates the symmetric pair. It compares
strings rather than numbers, which is fine -- any total order works for dedup.
The CASE expression orders each team pair by name so `count(DISTINCT ...)` does
not count {X,Y} and {Y,X} separately.
"""

from __future__ import annotations

#: Q3 -- people who are the only bridge between two otherwise-disconnected teams.
#:
#: Team membership is read through MEMBER_OF rather than a denormalised property
#: so the model stays a graph rather than a table with edges attached.
BROKERS_CYPHER = """
MATCH (a:Person)-[:KNOWS]-(b:Person)-[:KNOWS]-(c:Person)
WHERE elementId(a) < elementId(c)
  AND size([(a)-[:KNOWS]-(c) | 1]) = 0
MATCH (a)-[:MEMBER_OF]->(ta:Team)
MATCH (c)-[:MEMBER_OF]->(tc:Team)
WHERE ta <> tc
WITH b, count(DISTINCT CASE WHEN ta.name < tc.name
       THEN [ta.name, tc.name] ELSE [tc.name, ta.name] END) AS bridged_pairs
RETURN b.id AS person_id, b.name AS name, b.title AS title, bridged_pairs
ORDER BY bridged_pairs DESC, name ASC
LIMIT $limit
"""

#: Q4 -- skills on a project held by exactly one person.
#:
#: `collect(DISTINCT {id: p.id, name: p.name})` before the `size(...) = 1`
#: check is what makes this count distinct holders rather than distinct
#: (person, edge) pairs: the same person reachable twice through different
#: WORKS_ON/HAS_SKILL paths must still read as one holder, not two.
#:
#: Dedupes on `p.id`, not `p.name`. `DISTINCT` on a bare name would collapse
#: two different people who happen to share a name into one "holder" --
#: correctness would then depend on the generator's name-uniqueness
#: discipline (a `used` set, `scripts/generate.py`) and the absence of any
#: other `Person`-creating code path, rather than on the database. Neither of
#: those is a schema-level guarantee: there is no uniqueness constraint on
#: `Person.name` in the migrations, only on `Person.id` (migration 0001).
#: Dedup now rests on the constraint that actually exists. Re-verified
#: against live data after this change: the result set is identical to the
#: name-keyed form, as expected on a graph where every seeded name already
#: happens to be unique.
BUS_FACTOR_CYPHER = """
MATCH (pr:Project)<-[:WORKS_ON]-(p:Person)-[:HAS_SKILL]->(s:Skill)
WITH pr, s, collect(DISTINCT {id: p.id, name: p.name}) AS holders
WHERE size(holders) = 1
RETURN pr.name AS project, s.name AS skill, holders[0].name AS sole_holder
ORDER BY project ASC, skill ASC
LIMIT $limit
"""
