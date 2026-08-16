"""Tests for the lifespan's VOUCH_SKIP_STARTUP_PROBE escape hatch.

Unit-only: ``GraphClient.connect`` is monkeypatched to a recording fake so
these run with no live database regardless of which branch is under test --
that's the whole point of the flag, so the test proving it works must not
itself depend on the thing it is proving unnecessary.
"""

from __future__ import annotations

import pytest
from veloce import Veloce

from app.core.lifespan import lifespan


class _RecordingGraphClient:
    """Stands in for GraphClient just long enough to see whether .check() ran."""

    def __init__(self) -> None:
        self.check_called = False
        self.closed = False

    async def check(self) -> tuple[bool, str]:
        self.check_called = True
        return True, "ok"

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture
def recording_graph(monkeypatch: pytest.MonkeyPatch) -> _RecordingGraphClient:
    graph = _RecordingGraphClient()
    monkeypatch.setattr("app.core.lifespan.GraphClient.connect", lambda settings: graph)
    return graph


async def test_the_probe_is_skipped_when_the_flag_is_set(
    recording_graph: _RecordingGraphClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VOUCH_SKIP_STARTUP_PROBE", "1")
    app = Veloce()
    async with lifespan(app):
        assert recording_graph.check_called is False
    assert recording_graph.closed is True


async def test_the_probe_still_runs_when_the_flag_is_absent(
    recording_graph: _RecordingGraphClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("VOUCH_SKIP_STARTUP_PROBE", raising=False)
    app = Veloce()
    async with lifespan(app):
        assert recording_graph.check_called is True
    assert recording_graph.closed is True
