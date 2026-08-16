"""CognoDB driver lifecycle, connection pooling and session management.

Async, deliberately
-------------------
Veloce is an ASGI framework, so route handlers run on an event loop. The
*synchronous* neo4j driver does blocking socket I/O; calling it from a coroutine
stalls the entire loop for the duration of every query, and one slow traversal
freezes every other in-flight request. So this module uses
``AsyncGraphDatabase`` throughout. Command-line entry points (the migration
runner, the seed loader) wrap it in ``asyncio.run``.

One driver per process
----------------------
The driver *is* the connection pool. It is created once at application startup,
stored on the app, and closed at shutdown. Constructing one per request would
open a fresh TCP+TLS connection every time and exhaust the instance's
connection budget almost immediately.

Sessions, by contrast, are cheap and must be short-lived: one per unit of work,
always closed. Every session in this module is acquired through an
``async with`` block, so the connection returns to the pool even if the body
raises.
"""

from __future__ import annotations

import time
from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from types import TracebackType
from typing import Any, Self

from neo4j import AsyncDriver, AsyncGraphDatabase, AsyncSession, Query, RoutingControl
from neo4j.exceptions import AuthError, ClientError, Neo4jError, ServiceUnavailable

from app.core.exceptions import GraphUnavailableError, QueryTimeoutError
from app.core.logging import get_logger
from app.core.settings import Settings

#: ``get_logger`` rather than ``logging.getLogger(__name__)`` -- every other
#: module in this application logs under the ``vouch.*`` namespace so an
#: operator can raise or lower this application's verbosity as a whole
#: without touching the neo4j driver's own logger. Using the raw module path
#: here would have quietly opted this module out of that.
log = get_logger("db")

#: Server-side codes for a transaction killed by its own timeout.
_TIMEOUT_CODES = frozenset(
    {
        "Neo.ClientError.Transaction.TransactionTimedOut",
        "Neo.ClientError.Transaction.TransactionTimedOutClientConfiguration",
    }
)

# --- Pool sizing -----------------------------------------------------------
#
# The free (c0) instance allows 200 concurrent connections in total, shared by
# everything that connects: this app, the migration runner, the seed loader,
# your psql-equivalent shell, and the CognoDB console.
#
# The number that must stay under 200 is (worker processes x MAX_POOL_SIZE),
# not MAX_POOL_SIZE alone -- each uvicorn worker is a separate process with its
# own driver and therefore its own pool. That product is the thing people get
# wrong when they scale workers up and start seeing connection refusals.
#
# 20 per worker is generous for the actual workload: the instance is a
# burstable 0.5 vCPU, so it cannot usefully serve more than a handful of
# concurrent traversals anyway. Queueing in our pool is preferable to piling
# concurrent work onto a database that will just thrash.
MAX_POOL_SIZE = 20

#: Give up waiting for a free connection after this long. The default is 60s,
#: which is far past the point a browser (or the user) has given up. Failing at
#: 10s produces a visible 503 with a retry action instead of a hung tab.
ACQUISITION_TIMEOUT_S = 10.0

#: Retire pooled connections after 5 minutes. The default is an hour, but
#: managed tiers and the proxies in front of them silently drop idle TCP
#: connections well before that; recycling early avoids handing a request a
#: socket the far end has already forgotten about.
MAX_CONNECTION_LIFETIME_S = 300

#: If a pooled connection has been idle longer than this, ping it before
#: handing it out. Unset by default. This is the specific fix for "the first
#: request after a quiet period fails, the retry succeeds" -- which is exactly
#: what a free tier plus a spun-down Render service produces. Costs one extra
#: round trip, and only on connections that were actually idle.
LIVENESS_CHECK_TIMEOUT_S = 30.0

#: Bound how long managed transactions keep retrying transient failures. The
#: default 30s means a request against a downed database hangs for half a
#: minute before reporting anything.
MAX_TRANSACTION_RETRY_TIME_S = 15.0

#: TCP+TLS connect budget for a single attempt.
CONNECTION_TIMEOUT_S = 10.0


def _to_python(value: Any) -> Any:
    """Convert driver-native temporals to standard library types.

    The neo4j driver returns its own DateTime/Date/Time classes, which carry
    nanosecond precision Python cannot represent and which pydantic refuses.
    Converting here rather than in a model keeps the driver's type hierarchy
    from leaking above app/db, which is the one rule this layer exists to hold.

    Note the alternative that does NOT work: CognoDB's toString() on a temporal
    returns a struct dump like "{{2026 8 16} {13 19 42 769114387} 0}", and
    epochMillis is not implemented -- so the native value is the only correct
    thing to ask for.

    Recurses through lists and dicts because query results nest freely --
    ``collect(DISTINCT {company: ..., from_year: ...})`` puts a temporal inside
    a map inside a list, and a shallow conversion would miss it.
    """
    if hasattr(value, "to_native"):
        return value.to_native()
    if isinstance(value, list):
        return [_to_python(item) for item in value]
    if isinstance(value, dict):
        return {key: _to_python(item) for key, item in value.items()}
    return value


def build_driver(settings: Settings) -> AsyncDriver:
    """Construct the driver and its pool.

    Does not connect: the pool is lazy, so this cannot fail because the database
    is down. That is what lets the app boot and report the problem through
    ``/ready`` instead of crash-looping -- see :meth:`Database.check`.
    """
    return AsyncGraphDatabase.driver(
        settings.cognodb_uri,
        auth=(settings.cognodb_user, settings.cognodb_password.get_secret_value()),
        max_connection_pool_size=MAX_POOL_SIZE,
        connection_acquisition_timeout=ACQUISITION_TIMEOUT_S,
        connection_timeout=CONNECTION_TIMEOUT_S,
        max_connection_lifetime=MAX_CONNECTION_LIFETIME_S,
        liveness_check_timeout=LIVENESS_CHECK_TIMEOUT_S,
        max_transaction_retry_time=MAX_TRANSACTION_RETRY_TIME_S,
        keep_alive=True,
        user_agent="vouch/0.1.0",
    )


class GraphClient:
    """Owns the driver and speaks the application's error taxonomy.

    The neo4j exception hierarchy stops here: everything above this class
    catches :mod:`app.errors` types only.

    Usable as an async context manager, which is how scripts should hold it::

        async with GraphClient.connect(settings) as graph:
            rows = await graph.read("RETURN 1 AS ok")
        # driver closed, pool drained, even if the body raised
    """

    def __init__(self, driver: AsyncDriver, settings: Settings) -> None:
        self._driver = driver
        self._settings = settings

    # -- lifecycle ---------------------------------------------------------

    @classmethod
    def connect(cls, settings: Settings) -> Self:
        """Build the pool. Cheap and non-blocking; no I/O happens yet."""
        return cls(build_driver(settings), settings)

    async def aclose(self) -> None:
        """Close the driver and every pooled connection.

        Called from the ASGI lifespan shutdown hook. Skipping this leaks
        sockets on the instance's 200-connection budget across restarts, which
        on a free tier is a real way to lock yourself out of your own database.
        """
        await self._driver.close()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    @asynccontextmanager
    async def session(self, *, readonly: bool = True) -> AsyncGenerator[AsyncSession]:
        """Yield a session and guarantee its connection returns to the pool.

        Sessions are per-unit-of-work and must not be shared between requests or
        held open across awaits that do unrelated work -- a session holds a
        connection for its whole lifetime, so a long-lived one is a connection
        permanently removed from a pool of twenty.
        """
        session = self._driver.session(
            default_access_mode="READ" if readonly else "WRITE",
        )
        try:
            yield session
        finally:
            await session.close()

    # -- queries -----------------------------------------------------------

    async def read(
        self,
        cypher: str,
        params: Mapping[str, Any] | None = None,
        *,
        timeout: float | None = None,
        name: str | None = None,
    ) -> list[dict[str, Any]]:
        """Run a read query in a managed transaction and return plain dicts.

        Managed transactions (``execute_read``) rather than raw ``session.run``:
        the driver then retries transient failures with exponential backoff
        itself, which is why there is no hand-rolled retry loop in this codebase.

        Records are materialised inside the transaction on purpose -- a
        ``Result`` is invalid once its transaction closes, so returning one
        would blow up at the call site.

        ``name`` identifies this query in the timing log (see ``_log_query``);
        pass the Cypher module's own constant name (``PERSON_EXISTS_CYPHER``)
        when the caller has one -- it reads far better in a scrolling log than
        the query's own opening line.

        Raises:
            QueryTimeoutError: the traversal ran past its timeout.
            GraphUnavailableError: unreachable instance, or rejected credentials.
        """
        return await self._execute(cypher, params, timeout, RoutingControl.READ, name)

    async def write(
        self,
        cypher: str,
        params: Mapping[str, Any] | None = None,
        *,
        timeout: float | None = None,
        name: str | None = None,
    ) -> list[dict[str, Any]]:
        """Run a write query in a managed transaction.

        Used by the migration runner and the seed loader. The web application
        itself issues no writes at all -- see the README on why that is also the
        reason there is no CSRF token.

        See :meth:`read` for what ``name`` is for.
        """
        return await self._execute(cypher, params, timeout, RoutingControl.WRITE, name)

    async def _execute(
        self,
        cypher: str,
        params: Mapping[str, Any] | None,
        timeout: float | None,
        routing: RoutingControl,
        name: str | None = None,
    ) -> list[dict[str, Any]]:
        """Run one statement through a managed transaction.

        ``driver.execute_query`` rather than ``session.execute_read(fn)`` for a
        concrete reason: a transaction function receives an
        ``AsyncManagedTransaction``, whose ``run()`` *rejects* a ``Query``
        object ("Query object is only supported for session.run"), so there is
        no way to attach a per-statement timeout on that path.
        ``execute_query`` accepts a ``Query`` and is itself built on managed
        transactions, so it gives us the timeout *and* the driver's
        transient-failure retry with backoff.

        Records are materialised here because a ``Result`` is only valid inside
        its transaction. ``params`` is deliberately never passed to
        ``_log_query`` -- account statements carry a password hash as a
        parameter, and a timing log that echoed parameter values would be a
        credential leak sitting in a log file.
        """
        started = time.perf_counter()
        try:
            result = await self._driver.execute_query(
                self._query(cypher, timeout), dict(params or {}), routing_=routing
            )
        except (ServiceUnavailable, AuthError, ValueError) as exc:
            # ValueError belongs here, unintuitive as that looks. When the
            # host in COGNODB_URI does not resolve, the driver does not raise
            # ServiceUnavailable -- it raises a bare
            # `ValueError("Cannot resolve address ...")` from its DNS helper
            # (neo4j/_async_compat/network/_util.py). Without this, a
            # mistyped or down host escapes every handler as an unhandled
            # 500 with a driver stack trace, which is precisely the
            # "database unreachable" case that must degrade gracefully.
            # Verified by pointing the app at an unresolvable host.
            raise self._unavailable(exc) from exc
        except ClientError as exc:
            if exc.code in _TIMEOUT_CODES:
                raise QueryTimeoutError() from exc
            raise
        except Neo4jError:
            log.exception("query failed")
            raise

        rows = [_to_python(record.data()) for record in result.records]
        self._log_query(name or self._default_query_name(cypher), started, len(rows))
        return rows

    @staticmethod
    def _log_query(name: str, started: float, rows: int) -> None:
        """Emit one line per query. Real numbers become the README's timing table.

        Takes the name as an already-resolved string rather than deriving one
        from the Cypher here, so a caller with a meaningful constant name can
        pass it straight through -- see :meth:`read`.
        """
        log.info(
            "event=query name=%s duration_ms=%d rows=%d",
            name,
            int((time.perf_counter() - started) * 1000),
            rows,
        )

    @staticmethod
    def _default_query_name(cypher: str) -> str:
        """Fall back to the first non-blank line of the Cypher, truncated.

        Only used when a caller passes no ``name``. Imperfect on purpose --
        a multi-line write's first line is often just its opening ``MATCH``
        clause, which reads identically in a log to an unrelated read that
        happens to start the same way -- but "unknown" would be worse, and a
        caller that cares about a clearer name can supply one.
        """
        return next((line.strip() for line in cypher.splitlines() if line.strip()), "unknown")[:60]

    async def execute_schema(self, statement: str, *, timeout: float | None = None) -> None:
        """Run one statement in its own auto-commit transaction.

        Constraint and index creation cannot share a transaction with data
        writes on a Bolt-protocol database, so the migration runner drives each
        statement through this path rather than through :meth:`write`.
        """
        try:
            async with self.session(readonly=False) as session:
                result = await session.run(self._query(statement, timeout))
                await result.consume()
        except (ServiceUnavailable, AuthError, ValueError) as exc:
            # ValueError belongs here, unintuitive as that looks. When the
            # host in COGNODB_URI does not resolve, the driver does not raise
            # ServiceUnavailable -- it raises a bare
            # `ValueError("Cannot resolve address ...")` from its DNS helper
            # (neo4j/_async_compat/network/_util.py). Without this, a
            # mistyped or down host escapes every handler as an unhandled
            # 500 with a driver stack trace, which is precisely the
            # "database unreachable" case that must degrade gracefully.
            # Verified by pointing the app at an unresolvable host.
            raise self._unavailable(exc) from exc

    # -- health ------------------------------------------------------------

    async def check(self) -> tuple[bool, str]:
        """Readiness probe. Returns ``(ok, detail)`` and never raises.

        Uses ``verify_connectivity`` rather than a managed read on purpose: a
        managed transaction retries with backoff for up to
        ``MAX_TRANSACTION_RETRY_TIME_S``, so probing that way takes ~17s to
        report a database that is down -- long enough for a load balancer to
        give up, and useless exactly when it matters. A single attempt reports
        in well under a second.

        Deliberately total: a readiness endpoint that throws is one that lies.
        """
        try:
            await self._driver.verify_connectivity()
        except Exception as exc:  # noqa: BLE001 -- a probe reports, it does not propagate
            return False, f"{type(exc).__name__}: {exc}"
        return True, "ok"

    # -- internals ---------------------------------------------------------

    def _query(self, cypher: str, timeout: float | None) -> Query:
        """Attach a server-side timeout to every statement we send.

        ``execute_read``/``execute_write`` take no timeout argument, so the
        budget has to ride on the Query object. Without it a pathological
        traversal runs until the server gives up, holding a pooled connection
        the whole time.
        """
        return Query(cypher, timeout=timeout or self._settings.query_timeout_s)

    @staticmethod
    def _unavailable(exc: Exception) -> GraphUnavailableError:
        if isinstance(exc, AuthError):
            log.error("database rejected our credentials")
            return GraphUnavailableError("The graph database rejected our credentials.")
        log.error("database unreachable: %s", exc)
        return GraphUnavailableError()
