from __future__ import annotations

import pytest

from app.core.exceptions import InvalidInputError, ResourceNotFoundError
from app.models.person import ProfileUpdate
from app.services.person_service import PersonService
from tests.support.fake_graph import FakeGraph

PROFILE_ROW = {
    "id": "p0001",
    "name": "Priya Sharma",
    "title": "Staff Engineer",
    "seniority": "staff",
    "headline": "Payments platform.",
    "employment": [{"company": "Everline", "from_year": 2022, "to_year": None, "is_current": True}],
    "skills": ["Python", "Kafka"],
    "projects": ["Atlas"],
    "team": "Payments",
    "mutual_connections": ["Arjun Rao"],
}


async def test_get_profile_maps_a_row_to_the_domain_model() -> None:
    service = PersonService(FakeGraph({"OPTIONAL MATCH": [PROFILE_ROW]}))
    profile = await service.get_profile("p0001", viewer_id="me")
    assert profile.name == "Priya Sharma"
    assert profile.employment[0].is_current is True
    assert profile.mutual_connections == ["Arjun Rao"]


async def test_get_profile_raises_for_an_unknown_person() -> None:
    with pytest.raises(ResourceNotFoundError):
        await PersonService(FakeGraph({})).get_profile("ghost", viewer_id="me")


async def test_get_profile_passes_both_ids_as_parameters() -> None:
    graph = FakeGraph({"OPTIONAL MATCH": [PROFILE_ROW]})
    await PersonService(graph).get_profile("p0001", viewer_id="me")
    assert graph.calls[0].params == {"person_id": "p0001", "viewer_id": "me"}


async def test_update_profile_writes_only_the_supplied_fields() -> None:
    graph = FakeGraph({"SET p += $changes": [PROFILE_ROW], "OPTIONAL MATCH": [PROFILE_ROW]})
    await PersonService(graph).update_profile("p0001", ProfileUpdate(title="Principal Engineer"))
    write = next(call for call in graph.calls if call.write)
    assert write.params["changes"] == {"title": "Principal Engineer"}


async def test_update_profile_rejects_an_empty_patch() -> None:
    with pytest.raises(InvalidInputError):
        await PersonService(FakeGraph({})).update_profile("p0001", ProfileUpdate())


async def test_update_profile_raises_for_an_unknown_person() -> None:
    with pytest.raises(ResourceNotFoundError):
        await PersonService(FakeGraph({})).update_profile("ghost", ProfileUpdate(title="X"))


class _RogueUpdate(ProfileUpdate):
    """A patch claiming a field outside ProfileUpdate's own declared set.

    ProfileUpdate's fields and WRITABLE_FIELDS happen to be identical today,
    so nothing reachable through the real ``ProfileUpdate``/``ProfileUpdateRequest``
    path can exercise the rejection branch in ``update_profile`` -- the
    whitelist is defence-in-depth against the two sets drifting apart later
    (a new ``ProfileUpdate`` field added without a matching ``WRITABLE_FIELDS``
    entry), not against anything reachable today. This subclass is how that
    branch gets tested despite that.
    """

    def changed_fields(self) -> dict[str, object]:
        return {"password_hash": "pwned"}


async def test_update_profile_rejects_a_field_outside_the_writable_whitelist() -> None:
    with pytest.raises(InvalidInputError):
        await PersonService(FakeGraph({})).update_profile("p0001", _RogueUpdate())
