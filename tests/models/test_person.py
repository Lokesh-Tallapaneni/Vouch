from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.person import EmploymentRecord, PersonProfile, ProfileUpdate


def test_employment_record_marks_open_ended_tenure_as_current() -> None:
    record = EmploymentRecord(company="Acme", from_year=2021, to_year=None, is_current=True)
    assert record.is_current is True
    assert record.to_year is None


def test_profile_update_rejects_a_blank_name() -> None:
    with pytest.raises(ValidationError):
        ProfileUpdate(name="   ")


def test_profile_update_strips_surrounding_whitespace() -> None:
    assert ProfileUpdate(title="  Staff Engineer  ").title == "Staff Engineer"


def test_profile_update_is_empty_when_nothing_was_supplied() -> None:
    assert ProfileUpdate().changed_fields() == {}


def test_profile_update_reports_only_supplied_fields() -> None:
    assert ProfileUpdate(title="Staff Engineer").changed_fields() == {"title": "Staff Engineer"}


def test_an_explicit_null_is_treated_as_no_change() -> None:
    # null means "leave it alone", not "clear it" -- this app has no
    # clear-field operation, and honouring null would allow blanking a name.
    assert ProfileUpdate(title=None).changed_fields() == {}


def test_a_null_alongside_a_real_change_does_not_suppress_it() -> None:
    assert ProfileUpdate(title=None, headline="Payments.").changed_fields() == {
        "headline": "Payments."
    }


def test_person_profile_defaults_collections_to_empty() -> None:
    profile = PersonProfile(
        id="me", name="Lokesh", title="Engineer", seniority="senior", headline=""
    )
    assert profile.skills == [] and profile.mutual_connections == []
