"""Reading and updating person profiles."""

from __future__ import annotations

from typing import Any

from app.core.exceptions import InvalidInputError, ResourceNotFoundError
from app.core.logging import get_logger
from app.db.client import GraphClient
from app.db.cypher.people import (
    PERSON_NAME_CYPHER,
    PERSON_PROFILE_CYPHER,
    PERSON_SELF_PROFILE_CYPHER,
    UPDATE_PERSON_CYPHER,
)
from app.models.person import EmploymentRecord, PersonProfile, ProfileUpdate

log = get_logger("person_service")

#: The only properties the API may write. A patch key outside this set is
#: rejected before it reaches Cypher, so the endpoint cannot be used to set
#: arbitrary node properties.
WRITABLE_FIELDS = frozenset({"name", "title", "seniority", "headline"})


class PersonService:
    def __init__(self, graph: GraphClient) -> None:
        self._graph = graph

    async def get_profile(self, person_id: str, viewer_id: str | None) -> PersonProfile:
        # Looking at your own profile: skip the mutual-connections match
        # entirely rather than running it and discarding a self-referential
        # result -- see PERSON_SELF_PROFILE_CYPHER for why that match is
        # wrong, not just wasted, when viewer and subject are the same
        # person. update_profile's post-write re-read always lands here.
        if viewer_id is not None and viewer_id == person_id:
            rows = await self._graph.read(PERSON_SELF_PROFILE_CYPHER, {"person_id": person_id})
        else:
            rows = await self._graph.read(
                PERSON_PROFILE_CYPHER, {"person_id": person_id, "viewer_id": viewer_id or ""}
            )
        if not rows:
            raise ResourceNotFoundError("We couldn't find that person in the network.")
        return self._to_profile(rows[0])

    async def get_display_name(self, person_id: str) -> str | None:
        """Just a name, for a caller that has no use for the rest of a profile.

        Deliberately not built on ``get_profile``: that query is five
        chained ``OPTIONAL MATCH``es for a profile screen's worth of data,
        and calling it to read one field back off the result would still
        pay for all of it. ``None`` for an unknown person, matching every
        other "not found" outcome in this service that a header can render
        as "signed out" rather than as an error.
        """
        rows = await self._graph.read(PERSON_NAME_CYPHER, {"person_id": person_id})
        return str(rows[0]["name"]) if rows else None

    async def update_profile(self, person_id: str, update: ProfileUpdate) -> PersonProfile:
        changes = update.changed_fields()
        if not changes:
            raise InvalidInputError("Nothing to update.")

        rejected = set(changes) - WRITABLE_FIELDS
        if rejected:
            raise InvalidInputError(f"Cannot update: {', '.join(sorted(rejected))}.")

        if not await self._graph.write(
            UPDATE_PERSON_CYPHER, {"person_id": person_id, "changes": changes}
        ):
            raise ResourceNotFoundError("We couldn't find that person in the network.")

        log.info("updated %s fields on person %s", len(changes), person_id)
        return await self.get_profile(person_id, viewer_id=person_id)

    @staticmethod
    def _to_profile(row: dict[str, Any]) -> PersonProfile:
        """Map a result row to the domain model.

        OPTIONAL MATCH yields collect() entries full of nulls when a person has
        no employment at all; those are filtered here rather than in Cypher,
        where the guard would obscure the query.
        """
        employment = [
            EmploymentRecord(
                company=entry["company"],
                from_year=entry["from_year"],
                to_year=entry.get("to_year"),
                is_current=bool(entry.get("is_current")),
            )
            for entry in row.get("employment", [])
            if entry and entry.get("company")
        ]
        employment.sort(key=lambda record: (not record.is_current, -record.from_year))

        return PersonProfile(
            id=row["id"],
            name=row["name"],
            title=row.get("title") or "",
            seniority=row.get("seniority") or "",
            headline=row.get("headline") or "",
            employment=employment,
            skills=sorted(name for name in row.get("skills", []) if name),
            projects=sorted(name for name in row.get("projects", []) if name),
            team=row.get("team"),
            mutual_connections=sorted(name for name in row.get("mutual_connections", []) if name),
        )
