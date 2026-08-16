// Backs the typeahead. Prefix search (STARTS WITH) uses a range index;
// substring search would need a full-text index, which is a deliberate scope
// line documented in the README.
CREATE INDEX person_name IF NOT EXISTS FOR (p:Person) ON (p.name);
CREATE INDEX company_industry IF NOT EXISTS FOR (c:Company) ON (c.industry);
