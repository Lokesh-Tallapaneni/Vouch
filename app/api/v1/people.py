"""Person endpoints.

``PATCH /people/me`` rather than ``PATCH /people/{id}``: the resource being
edited is always the caller's own profile, so the identity comes from the
session and can never be supplied by the client. That removes a whole class of
authorisation bug by construction rather than by check.
"""

from __future__ import annotations

from veloce import Router

from app.api.dependencies import PersonServiceDep, RequiredAccount, ViewerId
from app.models.person import ProfileUpdate
from app.schemas.common import AUTH_RESPONSES, ERROR_RESPONSES
from app.schemas.person import PersonProfileResponse, ProfileUpdateRequest

router = Router(prefix="/people", tags=["people"])


@router.get(
    "/{person_id}",
    response_model=PersonProfileResponse,
    summary="Get a person's profile",
    response_description="The person, with employment history, skills and mutual connections.",
    responses=ERROR_RESPONSES,
)
async def get_person_profile(
    person_id: str, people: PersonServiceDep, viewer_id: ViewerId
) -> PersonProfileResponse:
    """One person's profile, including mutual connections with the viewer.

    Public: no account required, which is what keeps the demo usable.
    """
    profile = await people.get_profile(person_id, viewer_id=viewer_id)
    return PersonProfileResponse.model_validate(profile, from_attributes=True)


@router.patch(
    "/me",
    response_model=PersonProfileResponse,
    summary="Update my profile",
    response_description="The profile after the update.",
    responses=AUTH_RESPONSES,
)
async def update_my_profile(
    payload: ProfileUpdateRequest, account: RequiredAccount, people: PersonServiceDep
) -> PersonProfileResponse:
    """Update the signed-in user's own profile.

    The path is /me rather than /{person_id}: the resource is always the
    caller's own profile, so identity comes from the session and can never
    be supplied by the client. That removes an authorisation bug class by
    construction rather than by check.
    """
    update = ProfileUpdate.model_validate(payload.model_dump(exclude_unset=True))
    profile = await people.update_profile(account.person_id, update)
    return PersonProfileResponse.model_validate(profile, from_attributes=True)
