"""The seed dataset, as data rather than as side effects.

Generation and loading are separate steps with a serialisable artefact between
them. That artefact is committed, so the graph a reviewer loads is byte-identical
to the one the screenshots were taken from -- and so loading needs no RNG.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PersonSeed(BaseModel):
    id: str
    name: str
    title: str
    seniority: str
    headline: str


class CompanySeed(BaseModel):
    name: str
    industry: str


class EmploymentSeed(BaseModel):
    person_id: str
    company: str
    from_year: int
    to_year: int | None
    is_current: bool


class MembershipSeed(BaseModel):
    person_id: str
    team: str


class AssignmentSeed(BaseModel):
    person_id: str
    project: str


class SkillSeed(BaseModel):
    person_id: str
    skill: str
    level: str


class AcquaintanceSeed(BaseModel):
    from_id: str
    to_id: str
    strength: float
    since: int
    context: str


class NetworkSnapshot(BaseModel):
    people: list[PersonSeed] = Field(default_factory=list)
    companies: list[CompanySeed] = Field(default_factory=list)
    teams: list[str] = Field(default_factory=list)
    projects: list[dict[str, int | str]] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    employments: list[EmploymentSeed] = Field(default_factory=list)
    memberships: list[MembershipSeed] = Field(default_factory=list)
    assignments: list[AssignmentSeed] = Field(default_factory=list)
    skill_links: list[SkillSeed] = Field(default_factory=list)
    acquaintances: list[AcquaintanceSeed] = Field(default_factory=list)
