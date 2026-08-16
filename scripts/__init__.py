"""Operational entry points that are run by hand or by CI, not imported by the app.

Kept separate from ``app`` because these scripts own a process lifecycle
(``asyncio.run``, argument parsing, exit codes) that the ASGI app never does.
"""

from __future__ import annotations
