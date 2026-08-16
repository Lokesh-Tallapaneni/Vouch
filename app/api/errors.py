"""Exception handlers.

One place turns a VouchError into a response, so adding a failure mode means
adding an exception class and nothing else. The internal message is logged; the
user sees ``user_message``, which by construction says what happened and what to
do next -- never a stack trace, a driver class name, or a Cypher fragment.

Registering on the base :class:`~app.core.exceptions.VouchError` catches every
subclass, including ones defined outside ``app.core.exceptions`` (an account
service, say) -- Veloce's dispatcher walks the raised exception's MRO looking
for a registered handler, so a base-class registration is not a guess about
framework behaviour but the documented mechanism.

That same MRO walk is why this module also registers a handler on
``HTTPException``, not just ``VouchError`` and ``Exception``.
``HTTPException.__mro__`` includes ``Exception`` -- Veloce's own control-flow
exceptions descend from it, e.g. ``require_account`` raising 401 and a
malformed request body raising ``RequestValidationError`` (422) -- so a
catch-all registered on bare ``Exception`` would otherwise intercept those
too and turn a deliberate, well-formed response into an opaque 500. Confirmed
against ``veloce/app/dispatch.py``'s dispatch loop, not assumed: it catches
``HTTPException`` first and looks up a handler by walking *that* exception's
MRO, so the most specific registration -- ``HTTPException`` itself, here --
wins over the broader ``Exception`` handler.
"""

from __future__ import annotations

from veloce import JSONResponse, Request, Veloce
from veloce.exceptions import HTTPException

from app.core.exceptions import VouchError
from app.core.logging import get_logger

log = get_logger("errors")


async def handle_vouch_error(request: Request, exc: VouchError) -> JSONResponse:
    """Map a deliberate application error to its status code.

    Severity, not uniformity, decides the log level: a 404 is routine traffic
    and would just add noise at ``error`` level; a 5xx means something this
    application was supposed to prevent happened anyway, and needs the same
    attention an unhandled exception gets.
    """
    if exc.status_code >= 500:
        log.error("%s on %s: %s", type(exc).__name__, request.url.path, exc)
    else:
        log.info("%s on %s", type(exc).__name__, request.url.path)
    return JSONResponse({"detail": exc.user_message}, status_code=exc.status_code)


async def handle_http_exception(request: Request, exc: HTTPException) -> JSONResponse:
    """Preserve Veloce's own status code and detail for a framework exception.

    Not a hand-rolled reimplementation for its own sake: with no handler
    registered here at all, Veloce answers an ``HTTPException`` this same way
    by default. Registering this is purely defensive, to stop the broader
    ``Exception`` handler below from shadowing that default (see the module
    docstring). Deliberately does not delegate back into the app's own
    ``handle_http_exception`` method -- that method re-runs the same MRO
    lookup that found *this* handler, which would recurse.

    ``exc.errors`` carries the structured per-field list on a
    ``RequestValidationError``; anything else has only ``exc.detail``, a
    string. Both are already public-safe -- the framework raises these from
    known, deliberate call sites, never from an internal failure.
    """
    if exc.status_code >= 500:
        log.error("%s on %s: %s", type(exc).__name__, request.url.path, exc.detail)
    else:
        log.info("%s on %s", type(exc).__name__, request.url.path)
    structured = getattr(exc, "errors", None)
    detail = structured if structured is not None else (exc.detail or "Error")
    return JSONResponse({"detail": detail}, status_code=exc.status_code, headers=exc.headers)


async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all. Logs the real cause, tells the user nothing about internals.

    An unhandled exception reaching here is a bug, so it is logged with a full
    traceback -- but the response body must never carry it, because it would
    leak the schema, the driver version and the file layout. This handler is a
    safety net, not a place to be clever: the message is a fixed string, never
    the exception interpolated into the response.
    """
    log.exception("unhandled error on %s", request.url.path)
    return JSONResponse({"detail": "Something went wrong on our side."}, status_code=500)


def register_exception_handlers(app: Veloce) -> None:
    """Wire all three handlers onto the app. Call once, from create_app().

    Order of registration doesn't matter -- Veloce looks up a handler by the
    raised exception's own MRO, not by registration order -- but the set
    matters: ``HTTPException`` must be registered alongside ``Exception``, or
    the broader handler shadows it (see the module docstring).
    """
    app.exception_handler(VouchError)(handle_vouch_error)
    app.exception_handler(HTTPException)(handle_http_exception)
    app.exception_handler(Exception)(handle_unexpected_error)
