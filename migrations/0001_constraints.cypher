// Uniqueness constraints. These exist before any data is loaded: without a
// unique constraint on Person.id, MERGE in the loader silently creates
// duplicate people, and every path query then returns doubled routes.
CREATE CONSTRAINT person_id IF NOT EXISTS
  FOR (p:Person) REQUIRE p.id IS UNIQUE;

CREATE CONSTRAINT company_name IF NOT EXISTS
  FOR (c:Company) REQUIRE c.name IS UNIQUE;

CREATE CONSTRAINT skill_name IF NOT EXISTS
  FOR (s:Skill) REQUIRE s.name IS UNIQUE;

CREATE CONSTRAINT project_name IF NOT EXISTS
  FOR (pr:Project) REQUIRE pr.name IS UNIQUE;

CREATE CONSTRAINT team_name IF NOT EXISTS
  FOR (t:Team) REQUIRE t.name IS UNIQUE;
