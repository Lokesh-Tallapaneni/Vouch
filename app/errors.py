"""Error taxonomy.

Every failure mode the application can hit maps to exactly one exception, one
HTTP status, and one thing the user sees. Nothing reaches the browser as a
stack trace.

| Condition                   | Exception          | HTTP | User sees                        |
|-----------------------------|--------------------|------|----------------------------------|
| Missing config at boot      | ConfigError        |  --  | Process refuses to start         |
| Database unreachable / auth | DatabaseUnavailable| 503  | Error panel with a retry action  |
| Query exceeded its timeout  | QueryTimeout       | 504  | "Took too long -- try fewer hops"|
| Person/company not in graph | NotFound           | 404  | 404 page with starting points    |
| Bad query parameters        | InvalidInput       | 422  | Inline field message             |
"""

from __future__ import annotations

from app.config import ConfigError

__all__ = [
    "ConfigError",
    "VouchError",
    "DatabaseUnavailable",
    "QueryTimeout",
    "NotFound",
    "InvalidInput",
]


class VouchError(Exception):
    """Base class for errors this application raises deliberately."""

    status_code: int = 500
    #: Shown to the user. Says what happened and what to do next.
    user_message: str = "Something went wrong on our side."

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.user_message)
        if message:
            self.user_message = message


class DatabaseUnavailable(VouchError):
    """The graph could not be reached, or refused our credentials.

    Raised instead of letting the driver's ServiceUnavailable/AuthError escape,
    so routes have a single thing to catch.
    """

    status_code = 503
    user_message = "Can't reach the graph database right now."


class QueryTimeout(VouchError):
    """A traversal ran past its timeout and was cancelled."""

    status_code = 504
    user_message = "That search took too long. Try a shorter path or a different target."


class NotFound(VouchError):
    """A person or company id that isn't in the graph."""

    status_code = 404
    user_message = "We couldn't find that in the network."


class InvalidInput(VouchError):
    """Parameters failed validation at the route boundary."""

    status_code = 422
    user_message = "That request didn't look right."
