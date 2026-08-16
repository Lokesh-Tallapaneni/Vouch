"""Shared fixtures.

``tests/`` is importable as a package so support modules can be imported by
path; that is why every directory under it has an ``__init__.py``.
"""

from __future__ import annotations

import pytest

from tests.support.fake_graph import FakeGraph


@pytest.fixture
def fake_graph() -> FakeGraph:
    """An empty graph. Tests fill in the rows they need."""
    return FakeGraph()


@pytest.fixture(autouse=True)
def _skip_startup_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test skips the lifespan's real connectivity probe.

    Without this, any test that boots the app through
    ``TestClient(create_app())`` pays a real network round trip to the live
    graph on every single boot -- ~40 tests times ~500ms is a suite slow
    enough that people stop running it. See ``app.core.lifespan`` for what
    this flag does and, just as importantly, does not change: the graph is
    still built and still closed, and a genuinely unreachable database is
    still handled the same tolerant way it always was.

    Sanctioned opt-out: a test that genuinely wants the real probe (an
    ``@pytest.mark.integration`` test, say) can request the ``monkeypatch``
    fixture itself and call ``monkeypatch.delenv("VOUCH_SKIP_STARTUP_PROBE",
    raising=False)`` -- fixtures are function-scoped, so the test gets this
    same instance and its ``delenv`` wins. ``tests/core/test_lifespan.py``
    does exactly this to exercise the flag-absent branch; use it as the
    worked example rather than rediscovering the mechanism.
    """
    monkeypatch.setenv("VOUCH_SKIP_STARTUP_PROBE", "1")
