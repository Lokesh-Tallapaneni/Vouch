"""Tests for request-ID correlation and per-query timing logs.

Covers three things: the middleware pair installed in create_app() (request
IDs on every response, and that the request id surfaces as a quotable
reference on an error response), and app.db.client.GraphClient's query-timing
log line -- specifically that it fires on both read and write, that a
caller-supplied name is used instead of a derived one, and, the one that
matters most, that no parameter value (a person id, a password hash) can ever
reach the log.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from veloce import TestClient
from veloce.exceptions import HTTPException

from app.core.exceptions import ResourceNotFoundError
from app.core.settings import Settings
from app.db.client import GraphClient
from app.main import create_app


def test_every_response_carries_a_request_id() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/health")
    assert response.headers.get("x-request-id")


def test_two_requests_get_different_ids() -> None:
    with TestClient(create_app()) as client:
        first = client.get("/health").headers["x-request-id"]
        second = client.get("/health").headers["x-request-id"]
    assert first != second


def test_an_error_response_quotes_the_same_request_id_as_the_header() -> None:
    # Proves the wiring end to end: the id RequestIDMiddleware minted for
    # this request is the same one app.api.errors surfaces as a reference,
    # not a second, independently-generated value.
    app = create_app()

    @app.get("/_test/boom", include_in_schema=False)
    async def _raise() -> None:
        raise ResourceNotFoundError()

    with TestClient(app) as client:
        response = client.get("/_test/boom")
    assert response.status_code == 404
    body = response.json()
    assert body["reference"] == response.headers["x-request-id"]


def test_a_framework_http_exception_also_carries_the_reference() -> None:
    app = create_app()

    @app.get("/_test/unauth", include_in_schema=False)
    async def _raise() -> None:
        raise HTTPException(status_code=401, detail="Sign in to do that.")

    with TestClient(app) as client:
        response = client.get("/_test/unauth")
    body = response.json()
    assert body["reference"] == response.headers["x-request-id"]


def _settings_stub() -> Settings:
    return Settings(
        cognodb_uri="bolt+s://unit-test.invalid",
        cognodb_user="unit-test-user",
        cognodb_password="unit-test-password-not-real",
        jwt_secret="unit-test-jwt-secret-not-a-real-secret-000000",
    )


def _client_with_mocked_driver(rows: list[dict[str, Any]]) -> tuple[GraphClient, MagicMock]:
    """A GraphClient wired to a mocked neo4j driver -- no socket, real _execute.

    FakeGraph (tests/support) is the wrong tool here: it stands in *for*
    GraphClient in service tests, so it never runs GraphClient's own code.
    These tests are about GraphClient._execute/_log_query themselves, so the
    thing under test has to be the real class, with only the driver boundary
    replaced.
    """
    records = [MagicMock(data=MagicMock(return_value=row)) for row in rows]
    result = MagicMock(records=records)
    driver = MagicMock()
    driver.execute_query = AsyncMock(return_value=result)
    return GraphClient(driver, _settings_stub()), driver


@pytest.mark.asyncio
async def test_a_read_logs_event_query(caplog: pytest.LogCaptureFixture) -> None:
    graph, _driver = _client_with_mocked_driver([{"id": "me"}])
    caplog.set_level(logging.INFO, logger="vouch.db")
    await graph.read("MATCH (p:Person {id: $person_id}) RETURN p.id AS id")
    assert any("event=query" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_a_write_also_logs_event_query(caplog: pytest.LogCaptureFixture) -> None:
    # read and write both funnel through _execute -- pinned separately so a
    # future refactor that only wires one of the two paths fails loudly here
    # instead of silently under-logging every account creation.
    graph, _driver = _client_with_mocked_driver([{"id": "acc-1"}])
    caplog.set_level(logging.INFO, logger="vouch.db")
    await graph.write("MERGE (a:Account {id: $id}) RETURN a.id AS id")
    assert any("event=query" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_a_caller_supplied_name_is_used_verbatim(caplog: pytest.LogCaptureFixture) -> None:
    # The point: CREATE_ACCOUNT_CYPHER's first Cypher line is just its
    # opening MATCH clause -- indistinguishable in a log from an unrelated
    # person-existence check -- while its own constant name says exactly
    # what it does. A caller that knows that name should be able to pass it.
    graph, _driver = _client_with_mocked_driver([{"id": "acc-1"}])
    caplog.set_level(logging.INFO, logger="vouch.db")
    await graph.write(
        "MATCH (p:Person {id: $person_id})\nMERGE (a:Account {id: $id})",
        name="CREATE_ACCOUNT_CYPHER",
    )
    messages = [r.getMessage() for r in caplog.records]
    assert any("name=CREATE_ACCOUNT_CYPHER" in m for m in messages)
    assert not any("name=MATCH" in m for m in messages)


@pytest.mark.asyncio
async def test_without_a_name_it_falls_back_to_the_first_cypher_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    graph, _driver = _client_with_mocked_driver([{"id": "me"}])
    caplog.set_level(logging.INFO, logger="vouch.db")
    await graph.read("\n  MATCH (p:Person {id: $person_id}) RETURN p.id AS id  \n")
    messages = [r.getMessage() for r in caplog.records]
    assert any("name=MATCH (p:Person {id: $person_id}) RETURN p.id AS id" in m for m in messages)


@pytest.mark.asyncio
async def test_the_query_log_line_never_contains_a_parameter_value(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # The one that matters most: query parameters include person ids and, in
    # the account statements, a password hash. A timing log that echoes them
    # is a credential leak sitting in a log file.
    secret = "argon2id$do-not-print-me-3f9c2a1e"  # pragma: allowlist secret
    graph, _driver = _client_with_mocked_driver([{"id": "acc-1"}])
    caplog.set_level(logging.INFO, logger="vouch.db")
    await graph.write(
        "MERGE (a:Account {password_hash: $password_hash}) RETURN a.id AS id",
        {"password_hash": secret},
        name="CREATE_ACCOUNT_CYPHER",
    )
    log_text = "\n".join(r.getMessage() for r in caplog.records)
    assert secret not in log_text
    assert "event=query" in log_text
