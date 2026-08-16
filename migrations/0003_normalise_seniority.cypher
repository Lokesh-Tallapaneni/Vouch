// A data migration, not a schema one -- proof the runner handles both.
// Seniority is matched and filtered case-insensitively everywhere, so it is
// stored lowercase rather than normalised at every read site.
MATCH (p:Person)
WHERE p.seniority IS NOT NULL
SET p.seniority = toLower(p.seniority);
