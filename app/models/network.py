"""Network-health view models."""

from __future__ import annotations

from pydantic import BaseModel


class Broker(BaseModel):
    """Someone who is the only bridge between otherwise-disconnected teams."""

    person_id: str
    name: str
    title: str
    bridged_pairs: int


class BusFactorRisk(BaseModel):
    """A skill on a project held by exactly one person."""

    project: str
    skill: str
    sole_holder: str
