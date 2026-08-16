"""Logging configuration.

One place decides how the process logs, called once from the lifespan. Modules
elsewhere only ever call ``logging.getLogger(__name__)`` -- they never configure
handlers, because a library that configures the root logger fights whatever
imported it.
"""

from __future__ import annotations

import logging
import sys

from app.core.settings import Settings

#: Logger name prefix for everything this application emits, so operators can
#: raise or lower our verbosity without touching third-party loggers.
LOGGER_NAMESPACE = "vouch"

_LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s %(message)s"


def configure_logging(settings: Settings) -> None:
    """Install handlers and set levels for this process.

    Idempotent: calling it twice replaces handlers rather than stacking them,
    which would otherwise duplicate every line under a reloader.
    """
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    root.addHandler(handler)
    root.setLevel(settings.log_level)

    # The neo4j driver logs a full stack trace for every managed-transaction
    # retry. That is useful when debugging the driver and unreadable in a server
    # log, where the retry is expected behaviour we already surface via /ready.
    logging.getLogger("neo4j").setLevel(logging.ERROR)


def get_logger(name: str) -> logging.Logger:
    """Return a logger inside the application namespace."""
    return logging.getLogger(f"{LOGGER_NAMESPACE}.{name}")
