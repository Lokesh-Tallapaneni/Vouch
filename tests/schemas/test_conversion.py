from __future__ import annotations

from datetime import UTC, datetime

from app.models.account import Account
from app.models.person import EmploymentRecord, PersonProfile
from app.schemas.auth import AccountResponse
from app.schemas.person import EmploymentResponse, PersonProfileResponse


def test_account_response_is_built_from_the_model() -> None:
    account = Account(
        id="acc-1", email="a@b.com", person_id="me", created_at=datetime(2026, 8, 16, tzinfo=UTC)
    )
    assert AccountResponse.model_validate(account, from_attributes=True).email == "a@b.com"


def test_account_response_has_no_password_field_at_all() -> None:
    # Structural, not a habit: the schema cannot carry what it does not declare.
    assert "password_hash" not in AccountResponse.model_fields
    assert "password" not in AccountResponse.model_fields


def test_an_extra_field_on_the_source_is_dropped_not_echoed() -> None:
    class Leaky:
        id = "acc-1"
        email = "a@b.com"
        person_id = "me"
        created_at = datetime(2026, 8, 16, tzinfo=UTC)
        password_hash = "$argon2id$leaked"

    dumped = AccountResponse.model_validate(Leaky(), from_attributes=True).model_dump_json()
    assert "leaked" not in dumped


def test_person_profile_response_round_trips_nested_employment() -> None:
    profile = PersonProfile(
        id="p1",
        name="Priya Sharma",
        title="Staff Engineer",
        seniority="staff",
        headline="Payments.",
        employment=[EmploymentRecord(company="Everline", from_year=2022, is_current=True)],
        skills=["Python"],
    )
    response = PersonProfileResponse.model_validate(profile, from_attributes=True)
    assert response.employment[0].company == "Everline"
    assert response.employment[0].is_current is True


def test_every_response_field_is_documented() -> None:
    # An OpenAPI page with undocumented fields is barely better than no page.
    for name, field in PersonProfileResponse.model_fields.items():
        assert field.description, f"{name} has no description"


def test_response_fields_the_model_defaults_are_still_required_on_the_wire() -> None:
    # Required on a response is a promise the field is always present -- which it
    # is, because the model defaults it. Mirroring the model's defaults here would
    # weaken that promise and make the OpenAPI doc claim the field may be absent.
    assert PersonProfileResponse.model_fields["headline"].is_required()
    assert EmploymentResponse.model_fields["is_current"].is_required()


def test_a_profile_response_still_builds_from_a_model_using_its_defaults() -> None:
    profile = PersonProfile(id="p1", name="Priya Sharma", title="Staff Engineer", seniority="staff")
    assert PersonProfileResponse.model_validate(profile, from_attributes=True).headline == ""
