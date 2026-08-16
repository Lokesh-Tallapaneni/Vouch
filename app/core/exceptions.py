"""Application exception taxonomy.

Every failure mode maps to exactly one exception, one HTTP status, and one
user-visible state. Nothing reaches the browser as a stack trace.

| Condition                | Exception             | HTTP | User sees                    |
|--------------------------|-----------------------|------|------------------------------|
| Bad/missing config       | ConfigurationError    |  --  | Process refuses to start     |
| Graph unreachable / auth | GraphUnavailableError | 503  | Error panel, retry action    |
| Query hit its timeout    | QueryTimeoutError     | 504  | "Try fewer hops"             |
| Id absent from the graph | ResourceNotFoundError | 404  | 404 page, starting points    |
| Bad request parameters   | InvalidInputError     | 422  | Inline field message         |

Layers above :mod:`app.db` catch these types only; the neo4j exception
hierarchy is translated at the client boundary and never leaks upward.
"""

from __future__ import annotations

__all__ = [
    "VouchError",
    "ConfigurationError",
    "GraphUnavailableError",
    "QueryTimeoutError",
    "ResourceNotFoundError",
    "InvalidInputError",
]


class VouchError(Exception):
    """Base class for errors this application raises deliberately."""

    status_code: int = 500
    #: Shown to the user. States what happened and what to do next.
    user_message: str = "Something went wrong on our side."

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.user_message)
        if message:
            self.user_message = message


class ConfigurationError(VouchError):
    """A required setting is missing or malformed.

    Raised during startup, before the server binds. There is no useful degraded
    mode for "we don't know where the database is", so this one is fatal by
    design -- unlike :class:`GraphUnavailableError`, which is not.
    """

    status_code = 500
    user_message = "The application is misconfigured."


class GraphUnavailableError(VouchError):
    """The graph could not be reached, or it refused our credentials."""

    status_code = 503
    user_message = "Can't reach the graph database right now."


class QueryTimeoutError(VouchError):
    """A traversal ran past its timeout and was cancelled server-side."""

    status_code = 504
    user_message = "That search took too long. Try a shorter path or a different target."


class ResourceNotFoundError(VouchError):
    """A person or company identifier that isn't present in the graph."""

    status_code = 404
    user_message = "We couldn't find that in the network."


class InvalidInputError(VouchError):
    """Request parameters failed validation at the route boundary."""

    status_code = 422
    user_message = "That request didn't look right."
