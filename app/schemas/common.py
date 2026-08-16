"""Schemas shared across resources.

Declaring the error shape once, and attaching it to routes through
``ERROR_RESPONSES``, means the OpenAPI page documents failure as precisely as
success -- which is the half of an API most documents skip.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SchemaBase(BaseModel):
    """Base for every wire schema.

    ``from_attributes`` lets a schema be built straight from a model instance.
    ``extra="forbid"`` makes an unknown field in a *request* an error rather
    than something silently ignored -- a typo'd field name should fail loudly,
    not appear to work.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")


class ErrorResponse(SchemaBase):
    """The body every failing request returns. One shape, always."""

    detail: str = Field(
        description="What went wrong, in language safe to show a user.",
        examples=["We couldn't find that person in the network."],
    )
    reference: str | None = Field(
        default=None,
        description=(
            "The request's correlation id, to quote when reporting this error. "
            "Absent only if request-id assignment itself failed."
        ),
        examples=["3f2a1e9c-4b7d-4c2e-9f5a-1d6e8c0b7a42"],
    )


#: Attached to routes as ``responses=ERROR_RESPONSES``. Documents the failures
#: the error taxonomy can actually produce, so a client can code against them.
ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    404: {"model": ErrorResponse, "description": "Not present in the graph."},
    422: {"model": ErrorResponse, "description": "Request parameters failed validation."},
    503: {"model": ErrorResponse, "description": "The graph database is unreachable."},
    504: {"model": ErrorResponse, "description": "The traversal exceeded its timeout."},
}

#: For routes that additionally require an account.
AUTH_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse, "description": "Not signed in."},
    **ERROR_RESPONSES,
}
