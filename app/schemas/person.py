"""Person wire contract."""

from __future__ import annotations

from pydantic import Field

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
    """PATCH body. Every field optional; absent means "leave it alone"."""

    name: str | None = Field(default=None, max_length=120, description="Full name.")
    title: str | None = Field(default=None, max_length=120, description="Job title.")
    seniority: str | None = Field(default=None, max_length=40, description="Seniority band.")
    headline: str | None = Field(
        default=None, max_length=280, description="Short self-description."
    )
