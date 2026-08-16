"""CognoDB driver lifecycle.

One driver per process, created at application startup and closed at shutdown --
never per request. The driver owns a connection pool; constructing one per
request would exhaust the free tier's 200-connection budget almost immediately.

All reads go through managed transactions (``session.execute_read``). The driver
then retries transient failures with backoff on our behalf, which is why there
is no hand-rolled retry loop anywhere in this codebase.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from neo4j import Driver, GraphDatabase, ManagedTransaction, Query
from neo4j.exceptions import AuthError, ClientError, Neo4jError, ServiceUnavailable

from app.config import Settings
from app.errors import DatabaseUnavailable, QueryTimeout

log = logging.getLogger(__name__)

#: Server-side code for a transaction killed by its timeout.
_TIMEOUT_CODES = frozenset(
    {
        "Neo.ClientError.Transaction.TransactionTimedOut",
        "Neo.ClientError.Transaction.TransactionTimedOutClientConfiguration",
    }
)


def build_driver(settings: Settings) -> Driver:
    """Construct the driver. Does not connect -- the pool is lazy.

    Pool settings are tuned for a burstable free (c0) instance:

    * ``max_connection_pool_size=20`` -- well inside the 200-connection cap,
      leaving headroom for the migration runner and loader to run alongside.
    * ``max_connection_lifetime=300`` -- free tiers drop idle connections;
      recycling before that avoids handing a dead socket to a request.
    * ``max_transaction_retry_time=15`` -- bounds how long managed transactions
      keep retrying, so a request fails visibly instead of hanging.
    """
    return GraphDatabase.driver(
        settings.cognodb_uri,
        auth=(settings.cognodb_user, settings.cognodb_password.get_secret_value()),
        max_connection_pool_size=20,
        connection_acquisition_timeout=10,
        connection_timeout=10,
        max_connection_lifetime=300,
        max_transaction_retry_time=15,
    )


class Database:
    """Thin wrapper over the driver that speaks the application's error taxonomy.

    Everything above this class catches :mod:`app.errors` exceptions only; the
    neo4j exception hierarchy stops here.
    """

    def __init__(self, driver: Driver, settings: Settings) -> None:
        self._driver = driver
        self._settings = settings

    # -- lifecycle ---------------------------------------------------------

    @classmethod
    def connect(cls, settings: Settings) -> Database:
        return cls(build_driver(settings), settings)

    def close(self) -> None:
        self._driver.close()

    # -- queries -----------------------------------------------------------

    def read(
        self,
        cypher: str,
        params: Mapping[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> list[dict[str, Any]]:
        """Run a read query in a managed transaction and return plain dicts.

        Records are materialised inside the transaction: a ``Result`` is invalid
        once its transaction closes, so returning one would fail at the call site.

        Raises:
            QueryTimeout: the traversal ran past ``timeout``.
            DatabaseUnavailable: the instance is unreachable or refused auth.
        """
        query = Query(cypher, timeout=timeout or self._settings.query_timeout_s)  # type: ignore[arg-type]

        def _work(tx: ManagedTransaction) -> list[dict[str, Any]]:
            return [record.data() for record in tx.run(query, dict(params or {}))]

        try:
            with self._driver.session() as session:
                return session.execute_read(_work)
        except (ServiceUnavailable, AuthError) as exc:
            raise self._unavailable(exc) from exc
        except ClientError as exc:
            if exc.code in _TIMEOUT_CODES:
                raise QueryTimeout() from exc
            raise
        except Neo4jError as exc:
            log.exception("query failed", extra={"code": exc.code})
            raise

    def write(
        self,
        cypher: str,
        params: Mapping[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> list[dict[str, Any]]:
        """Run a write query in a managed transaction.

        Used by the migration runner and the seed loader. The web application
        itself is read-only -- see the README on why there is no CSRF token.
        """
        query = Query(cypher, timeout=timeout or self._settings.query_timeout_s)  # type: ignore[arg-type]

        def _work(tx: ManagedTransaction) -> list[dict[str, Any]]:
            return [record.data() for record in tx.run(query, dict(params or {}))]

        try:
            with self._driver.session() as session:
                return session.execute_write(_work)
        except (ServiceUnavailable, AuthError) as exc:
            raise self._unavailable(exc) from exc

    def execute_raw(self, statement: str, *, timeout: float | None = None) -> None:
        """Run a single statement in its own auto-commit transaction.

        Constraint and index creation cannot share a transaction with data
        writes on a Bolt-protocol database, so migrations run statement by
        statement through this path rather than through :meth:`write`.
        """
        try:
            with self._driver.session() as session:
                session.run(Query(statement, timeout=timeout)).consume()  # type: ignore[arg-type]
        except (ServiceUnavailable, AuthError) as exc:
            raise self._unavailable(exc) from exc

    # -- health ------------------------------------------------------------

    def check(self) -> tuple[bool, str]:
        """Readiness probe. Returns ``(ok, detail)`` and never raises.

        Uses ``verify_connectivity`` rather than a managed read on purpose. A
        managed transaction retries with backoff for up to
        ``max_transaction_retry_time`` seconds, so probing that way takes ~17s
        to report a database that is down -- long enough for a load balancer to
        time out and for ``/ready`` to be useless exactly when it matters.
        ``verify_connectivity`` makes a single attempt and reports immediately.

        Deliberately total: a readiness endpoint that throws is one that lies.
        """
        try:
            self._driver.verify_connectivity()
        except Exception as exc:  # noqa: BLE001 -- a probe reports, it does not propagate
            return False, f"{type(exc).__name__}: {exc}"
        return True, "ok"

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _unavailable(exc: Exception) -> DatabaseUnavailable:
        if isinstance(exc, AuthError):
            log.error("database rejected our credentials")
            return DatabaseUnavailable("The graph database rejected our credentials.")
        log.error("database unreachable: %s", exc)
        return DatabaseUnavailable()
