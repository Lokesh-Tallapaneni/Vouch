"""Network-health wire contract."""

from __future__ import annotations

from pydantic import Field

from app.schemas.common import SchemaBase


class BrokerResponse(SchemaBase):
    person_id: str = Field(description="Person identifier.", examples=["p0007"])
    name: str = Field(description="Full name.", examples=["Meera Nair"])
    title: str = Field(description="Job title.", examples=["Engineering Manager"])
    bridged_pairs: int = Field(
        description="Distinct team pairs this person is the only connection between.",
        examples=[7],
    )


class BusFactorRiskResponse(SchemaBase):
    project: str = Field(description="Project name.", examples=["Atlas"])
    skill: str = Field(description="Skill held by exactly one contributor.", examples=["Cypher"])
    sole_holder: str = Field(description="The only person on the project with it.")
