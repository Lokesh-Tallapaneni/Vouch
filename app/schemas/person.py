"""Person wire contract.

A response schema's "required" is a promise to the client, not a mirror of
how the model was constructed. ``EmploymentResponse.is_current`` and
``PersonProfileResponse.headline`` are required here even though
``EmploymentRecord.is_current`` and ``PersonProfile.headline`` default on the
model side, because the response *always* carries a value for them -- the
model's default guarantees that. Copying the model's optionality into the
response would only weaken that guarantee, telling an OpenAPI reader the
field might be absent when it never is. Field-for-field parity between
models and schemas is not the goal on its own; where the two layers say
different but individually correct things, the response says what the wire
actually promises.
"""

from __future__ import annotations

from pydantic import Field, field_validator

from app.schemas.common import SchemaBase


class EmploymentResponse(SchemaBase):
    company: str = Field(description="Employer name.", examples=["Everline"])
    from_year: int = Field(description="Year the stint began.", examples=[2022])
    to_year: int | None = Field(default=None, description="Year it ended; null if ongoing.")
    is_current: bool = Field(description="Whether this is the current employer.")


class PersonSummaryResponse(SchemaBase):
    id: str = Field(description="Person identifier.", examples=["p0042"])
    name: str = Field(description="Full name.", examples=["Priya Sharma"])
    title: str = Field(description="Job title.", examples=["Staff Engineer"])
    current_company: str | None = Field(default=None, description="Current employer, if any.")


class PersonProfileResponse(SchemaBase):
    id: str = Field(description="Person identifier.", examples=["p0042"])
    name: str = Field(description="Full name.", examples=["Priya Sharma"])
    title: str = Field(description="Job title.", examples=["Staff Engineer"])
    seniority: str = Field(description="Seniority band, lowercase.", examples=["staff"])
    headline: str = Field(description="Short self-description.", examples=["Payments platform."])
    employment: list[EmploymentResponse] = Field(
        default_factory=list, description="Employment history, current first."
    )
    skills: list[str] = Field(default_factory=list, description="Skills, alphabetical.")
    projects: list[str] = Field(default_factory=list, description="Projects worked on.")
    team: str | None = Field(default=None, description="Current team, if any.")
    mutual_connections: list[str] = Field(
        default_factory=list, description="People known to both this person and the viewer."
    )


class ProfileUpdateRequest(SchemaBase):
    """PATCH body. Every field optional; absent means "leave it alone".

    Rejects a whitespace-only value itself, at the wire boundary, rather than
    leaving that to ``ProfileUpdate`` underneath. Veloce parses this schema
    from the request body as part of routing, before the handler runs -- a
    ``ValidationError`` raised here becomes the framework's own 422. Built
    manually inside a handler instead (as ``ProfileUpdate`` briefly was),
    the identical error descends from neither ``HTTPException`` nor
    ``VouchError`` and falls through to the catch-all 500. ``ProfileUpdate``
    keeps the same check too, as defence in depth for any caller that
    reaches it without going through this schema.
    """

    name: str | None = Field(default=None, max_length=120, description="Full name.")
    title: str | None = Field(default=None, max_length=120, description="Job title.")
    seniority: str | None = Field(default=None, max_length=40, description="Seniority band.")
    headline: str | None = Field(
        default=None, max_length=280, description="Short self-description."
    )

    @field_validator("name", "title", "seniority", "headline")
    @classmethod
    def _strip_and_reject_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped
