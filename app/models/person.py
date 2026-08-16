"""Person-shaped view models.

These are the application's vocabulary: services return them, handlers and
templates consume them, and nothing above the service layer ever sees a raw
driver dict. Keeping the shape here means a change to a Cypher RETURN clause
breaks in one place instead of silently reshaping a template.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class EmploymentRecord(BaseModel):
    """One stint at one company.

    ``to_year is None`` means the stint is open-ended. Employment *history* is
    what lets a path cross a company boundary -- someone who left Acme two years
    ago is a route into Acme -- so this model is load-bearing, not decoration.
    """

    company: str
    from_year: int
    to_year: int | None = None
    is_current: bool = False


class PersonSummary(BaseModel):
    """Enough to render a search result or a row in a list."""

    id: str
    name: str
    title: str
    current_company: str | None = None


class PersonProfile(BaseModel):
    """Everything the profile screen renders, in one object."""

    id: str
    name: str
    title: str
    seniority: str
    headline: str = ""
    employment: list[EmploymentRecord] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)
    team: str | None = None
    mutual_connections: list[str] = Field(default_factory=list)


class ProfileUpdate(BaseModel):
    """A PATCH body: every field optional, absent means "leave it alone".

    The distinction between "absent" and "set to empty" matters -- without it a
    form that posts only one field would blank every other one.
    """

    name: str | None = Field(default=None, max_length=120)
    title: str | None = Field(default=None, max_length=120)
    seniority: str | None = Field(default=None, max_length=40)
    headline: str | None = Field(default=None, max_length=280)

    @field_validator("name", "title", "seniority", "headline")
    @classmethod
    def _strip_and_reject_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped

    def changed_fields(self) -> dict[str, Any]:
        """Only the fields the caller actually supplied.

        Driven by ``exclude_unset`` rather than by truthiness, so a field
        explicitly set to a falsy value is still an update.
        """
        return self.model_dump(exclude_unset=True, exclude_none=True)
