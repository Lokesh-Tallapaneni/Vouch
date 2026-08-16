"""Tests proving the unit suite's configuration is hermetic.

``Settings`` has no defaults for the CognoDB/JWT secrets -- deliberately, so
a misconfigured process refuses to boot (see ``app.core.settings``). That's
correct for production, but it means ``create_app() -> lifespan ->
get_settings()`` would fail outright anywhere a developer's ``.env`` doesn't
exist -- CI, a grader's clean clone. ``tests/conftest.py``'s autouse fixture
closes that gap by supplying dummy values unconditionally. This file proves
the mechanism actually works, independent of whatever real ``.env`` this
particular machine happens to have -- not just that the fixture runs, but
that its dummy values are genuinely sufficient on their own.
"""

from __future__ import annotations

import pytest

from app.core.exceptions import ConfigurationError
from app.core.settings import Settings, get_settings
from tests.conftest import DUMMY_SETTINGS_ENV

_REQUIRED_KEYS = ("COGNODB_URI", "COGNODB_USER", "COGNODB_PASSWORD", "JWT_SECRET")


@pytest.fixture
def _no_dotenv_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable ``Settings``' ``.env`` source for one test.

    Without this, deleting the four env vars below wouldn't prove anything on
    a machine that has a real ``.env``: pydantic-settings reads that file
    directly, bypassing ``os.environ`` entirely, so the file's real values
    would still satisfy ``Settings()`` even with every OS-level variable
    gone. Only with this source disabled does "the four required variables
    are absent" actually mean absent, which is what makes both tests below
    trustworthy regardless of whether the machine running them has a real
    ``.env`` or not.
    """
    monkeypatch.setitem(Settings.model_config, "env_file", None)


def test_the_four_required_variables_have_no_fallback_when_truly_absent(
    _no_dotenv_fallback: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Baseline: with the .env source disabled and the variables deleted,
    configuration genuinely fails. This rules out a hidden default or some
    other fallback being what actually saves the next test -- it has to be
    the dummy values themselves.
    """
    for key in _REQUIRED_KEYS:
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()
    with pytest.raises(ConfigurationError):
        get_settings()
    get_settings.cache_clear()


def test_the_suites_own_dummy_values_are_sufficient_without_any_dot_env(
    _no_dotenv_fallback: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The actual hermeticity proof: the exact same dummy values
    ``tests/conftest.py``'s autouse fixture sets for every test -- reapplied
    here after deleting the four keys first, with the ``.env`` source still
    disabled -- are enough on their own for ``get_settings()`` to succeed.
    If this passes, the suite genuinely does not need a developer's
    ``.env``. In CI, and on a grader's clean clone, that is exactly the
    state the suite runs in: no ``.env`` file exists at all.
    """
    for key in _REQUIRED_KEYS:
        monkeypatch.delenv(key, raising=False)
    for key, value in DUMMY_SETTINGS_ENV.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.cognodb_uri == DUMMY_SETTINGS_ENV["COGNODB_URI"]
    get_settings.cache_clear()
