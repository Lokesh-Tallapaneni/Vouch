"""Cypher for accounts.

Every statement in this package is a module-level constant taking parameters
only. No query is ever assembled from strings -- that is both an injection
guarantee and an explicit requirement of the brief, and keeping the statements
here makes it verifiable by grep rather than by reading every service.

Every ``created_at`` projection returns the native temporal (``a.created_at``),
never ``toString(a.created_at)``: on CognoDB that produces an unparseable
struct dump, and ``GraphClient`` already coerces native driver temporals to
``datetime`` while materialising rows -- see ``app/db/client.py::_to_python``.
"""

from __future__ import annotations

CREATE_ACCOUNT_CYPHER = """
MATCH (p:Person {id: $person_id})
MERGE (a:Account {email: $email})
  ON CREATE SET a.id            = $account_id,
                a.password_hash = $password_hash,
                a.created_at    = datetime()
MERGE (a)-[:IDENTIFIES]->(p)
RETURN a.id            AS id,
       a.email         AS email,
       a.created_at    AS created_at,
       p.id            AS person_id
"""

FIND_ACCOUNT_BY_EMAIL_CYPHER = """
MATCH (a:Account {email: $email})-[:IDENTIFIES]->(p:Person)
RETURN a.id            AS id,
       a.email         AS email,
       a.password_hash AS password_hash,
       a.created_at    AS created_at,
       p.id            AS person_id
"""

FIND_ACCOUNT_BY_ID_CYPHER = """
MATCH (a:Account {id: $account_id})-[:IDENTIFIES]->(p:Person)
RETURN a.id            AS id,
       a.email         AS email,
       a.created_at    AS created_at,
       p.id            AS person_id
"""

PERSON_EXISTS_CYPHER = "MATCH (p:Person {id: $person_id}) RETURN p.id AS id"
