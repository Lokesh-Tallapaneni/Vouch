"""Tests for app.api.errors -- exception-to-response mapping.

Exercises the handlers through throwaway routes registered on a test-local
app instance, not through real endpoints. The brief this test file grew from
targeted ``/api/v1/network/brokers`` and ``/api/v1/people/{id}``, but those
belong to Tasks 12 and 14 and don't exist yet -- and even once they do, a
route built just to raise the exception under test is the right shape for
this: it proves the *handler* maps the error correctly, and stays true
regardless of what those endpoints do later.
"""

from __future__ import annotations

from collections.abc import Callable

from veloce import TestClient
from veloce.exceptions import HTTPException, RequestValidationError

from app.core.exceptions import (
    GraphUnavailableError,
    InvalidInputError,
    QueryTimeoutError,
    ResourceNotFoundError,
)
from app.main import create_app
from app.services.account_service import EmailAlreadyRegisteredError


def _client_raising(path: str, make_exc: Callable[[], BaseException]) -> TestClient:
    """Build a real app via create_app() and add one route that always raises.

    Going through create_app() (rather than a bare Veloce()) proves the
    handlers registered there -- not a hand-rolled stand-in -- are what
    actually catches the error.
    """
    app = create_app()

    @app.get(path, include_in_schema=False)
    async def _raise() -> None:
        raise make_exc()

    return TestClient(app)


def test_graph_unavailable_error_maps_to_its_declared_status_and_message() -> None:
    with _client_raising("/_test/unavailable", GraphUnavailableError) as client:
        response = client.get("/_test/unavailable")
    assert response.status_code == GraphUnavailableError.status_code == 503
    assert response.json() == {"detail": GraphUnavailableError().user_message}


def test_resource_not_found_error_maps_to_its_declared_status_and_message() -> None:
    with _client_raising("/_test/missing", ResourceNotFoundError) as client:
        response = client.get("/_test/missing")
    assert response.status_code == ResourceNotFoundError.status_code == 404
    assert response.json() == {"detail": ResourceNotFoundError().user_message}


def test_query_timeout_error_maps_to_its_declared_status_and_message() -> None:
    with _client_raising("/_test/timeout", QueryTimeoutError) as client:
        response = client.get("/_test/timeout")
    assert response.status_code == QueryTimeoutError.status_code == 504
    assert response.json() == {"detail": QueryTimeoutError().user_message}


def test_invalid_input_error_maps_to_its_declared_status_and_message() -> None:
    with _client_raising("/_test/invalid", InvalidInputError) as client:
        response = client.get("/_test/invalid")
    assert response.status_code == InvalidInputError.status_code == 422
    assert response.json() == {"detail": InvalidInputError().user_message}


def test_a_vouch_error_subclass_defined_outside_core_exceptions_is_still_caught() -> None:
    # EmailAlreadyRegisteredError lives in app.services.account_service, not
    # app.core.exceptions. Registering the handler on VouchError only works
    # for this if Veloce's dispatch walks the MRO rather than matching an
    # explicit list of classes -- confirmed by reading veloce/app/errors.py's
    # _find_exception_handler before relying on it here.
    with _client_raising("/_test/conflict", EmailAlreadyRegisteredError) as client:
        response = client.get("/_test/conflict")
    assert response.status_code == EmailAlreadyRegisteredError.status_code == 409
    assert response.json() == {"detail": EmailAlreadyRegisteredError().user_message}


def test_an_unexpected_exception_becomes_a_generic_500() -> None:
    with _client_raising("/_test/boom", lambda: RuntimeError("cognodb_password=hunter2")) as client:
        response = client.get("/_test/boom")
    assert response.status_code == 500
    assert response.json() == {"detail": "Something went wrong on our side."}


def test_a_framework_http_exception_is_not_swallowed_by_the_catch_all() -> None:
    # HTTPException.__mro__ includes Exception, so a naive `Exception` handler
    # registration finds it via the same MRO walk that dispatch.py uses for
    # HTTPException itself -- and, being a broader class, would only win if
    # nothing more specific is registered on HTTPException. This is exactly
    # what require_account() relies on to turn an unauthenticated write into a
    # 401 rather than an opaque 500; regression-tested here directly, without
    # needing a real protected route.
    with _client_raising(
        "/_test/deliberate-401",
        lambda: HTTPException(status_code=401, detail="Sign in to do that."),
    ) as client:
        response = client.get("/_test/deliberate-401")
    assert response.status_code == 401
    assert response.json() == {"detail": "Sign in to do that."}


def test_a_request_validation_error_keeps_its_422_and_structured_detail() -> None:
    # RequestValidationError subclasses HTTPException (raised by veloce itself
    # when a request body fails pydantic validation) -- same MRO hazard as
    # above, different concrete exception, and different response shape
    # (a structured error list, not a plain string) worth pinning separately.
    errors = [{"loc": ["body", "password"], "msg": "too short", "type": "string_too_short"}]
    with _client_raising("/_test/bad-body", lambda: RequestValidationError(errors)) as client:
        response = client.get("/_test/bad-body")
    assert response.status_code == 422
    assert response.json() == {"detail": errors}


def test_no_response_body_ever_carries_a_traceback_class_name_or_internal_path() -> None:
    # The one that matters most: assert on the actual response text, not just
    # the status code. A 500 that leaks the schema or the driver is worse
    # than a 500 that doesn't.
    cases: dict[str, Callable[[], BaseException]] = {
        "/_test/leak-vouch": GraphUnavailableError,
        "/_test/leak-conflict": EmailAlreadyRegisteredError,
        "/_test/leak-unexpected": lambda: RuntimeError(
            "Traceback: neo4j.exceptions.ServiceUnavailable at app/db/client.py:239"
        ),
    }
    for path, make_exc in cases.items():
        with _client_raising(path, make_exc) as client:
            response = client.get(path)
        body = response.text
        assert "Traceback" not in body
        assert "neo4j" not in body
        assert "app.db" not in body
        assert "app/db" not in body
        assert "RuntimeError" not in body
        assert "GraphUnavailableError" not in body
