from __future__ import annotations

from app.core.security import (
    hash_account_password,
    issue_session_token,
    read_session_token,
    verify_account_password,
)
from app.models.account import SessionClaims

SECRET = "test-secret-that-is-long-enough-to-sign"


def test_hashing_never_returns_the_raw_password() -> None:
    assert hash_account_password("correct horse battery") != "correct horse battery"


def test_the_same_password_hashes_differently_each_time() -> None:
    # Distinct salts. Identical hashes would leak which accounts share a password.
    assert hash_account_password("same passphrase") != hash_account_password("same passphrase")


def test_the_correct_password_verifies() -> None:
    assert verify_account_password(
        "correct horse battery", hash_account_password("correct horse battery")
    )


def test_a_wrong_password_does_not_verify() -> None:
    assert not verify_account_password("wrong", hash_account_password("correct horse battery"))


def test_verifying_against_a_malformed_hash_returns_false_rather_than_raising() -> None:
    assert verify_account_password("anything", "not-a-hash") is False


def test_a_token_round_trips_its_claims() -> None:
    claims = SessionClaims(account_id="acc-1", person_id="me")
    assert read_session_token(issue_session_token(claims, SECRET), SECRET) == claims


def test_a_token_signed_with_another_secret_is_rejected() -> None:
    token = issue_session_token(SessionClaims(account_id="a", person_id="me"), SECRET)
    assert read_session_token(token, "a-different-secret-entirely") is None


def test_a_tampered_token_is_rejected() -> None:
    token = issue_session_token(SessionClaims(account_id="a", person_id="me"), SECRET)
    assert read_session_token(token[:-4] + "AAAA", SECRET) is None


def test_an_expired_token_is_rejected() -> None:
    token = issue_session_token(SessionClaims(account_id="a", person_id="me"), SECRET, ttl_hours=-1)
    assert read_session_token(token, SECRET) is None


def test_garbage_is_rejected_without_raising() -> None:
    assert read_session_token("not.a.token", SECRET) is None
