"""Tests for the driver-temporal-to-native coercion at the database boundary.

No live database: these exercise ``_to_python`` directly against a duck-typed
stand-in for a driver temporal, never ``neo4j.time``, so the test stays honest
about what the helper actually keys on -- the presence of ``to_native()``, not
a specific class.
"""

from __future__ import annotations

from datetime import datetime

from app.db.client import _to_python

_NATIVE = datetime(2026, 8, 16, 13, 19, 42, 769114)


class _FakeDriverTemporal:
    """Stands in for neo4j.time.DateTime/Date/Time -- anything with to_native()."""

    def to_native(self) -> datetime:
        return _NATIVE


def test_a_bare_driver_temporal_is_converted() -> None:
    assert _to_python(_FakeDriverTemporal()) == _NATIVE


def test_a_temporal_nested_in_a_list_is_converted() -> None:
    assert _to_python([_FakeDriverTemporal()]) == [_NATIVE]


def test_a_temporal_nested_in_a_dict_value_is_converted() -> None:
    assert _to_python({"created_at": _FakeDriverTemporal()}) == {"created_at": _NATIVE}


def test_a_temporal_nested_in_a_dict_inside_a_list_is_converted() -> None:
    payload = [{"company": "Acme", "from_year": _FakeDriverTemporal()}]
    assert _to_python(payload) == [{"company": "Acme", "from_year": _NATIVE}]


def test_scalars_pass_through_unchanged_and_keep_their_type() -> None:
    for value in ("a string", 1, 1.5, True, None):
        result = _to_python(value)
        assert result == value
        assert type(result) is type(value)
