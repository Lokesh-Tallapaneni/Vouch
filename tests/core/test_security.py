from __future__ import annotations

import base64
import json
import logging
import time

import pytest
from veloce import encode_jwt

from app.core.security import (
    hash_account_password,
    issue_session_token,
    read_session_token,
    verify_account_password,
)
from app.models.account import SessionClaims

SECRET = "test-secret-that-is-long-enough-to-sign"


def _b64url(data: bytes) -> str:
    """URL-safe base64 without padding -- what a JWT segment looks like."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


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


def test_a_token_signed_with_an_unlisted_algorithm_is_rejected() -> None:
    # The allow-list pins HS256. A token honestly signed with a different
    # algorithm must still be refused -- accepting it would mean the pin
    # does nothing.
    token = encode_jwt(
        {"sub": "a", "pid": "me", "exp": int(time.time()) + 3600}, SECRET, alg="HS512"
    )
    assert read_session_token(token, SECRET) is None


def test_an_unsigned_alg_none_token_is_rejected() -> None:
    # Hand-built rather than produced by encode_jwt, which refuses to emit
    # "none" at all -- this simulates an attacker crafting the token bytes
    # directly rather than us accidentally encoding one.
    header = _b64url(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    payload = _b64url(
        json.dumps({"sub": "a", "pid": "me", "exp": int(time.time()) + 3600}).encode()
    )
    token = f"{header}.{payload}."
    assert read_session_token(token, SECRET) is None


def test_a_token_missing_the_sub_claim_is_rejected() -> None:
    # Validly signed with the real secret, so this isolates claim validation
    # from signature verification.
    token = encode_jwt({"pid": "me", "exp": int(time.time()) + 3600}, SECRET, alg="HS256")
    assert read_session_token(token, SECRET) is None


def test_a_token_missing_the_pid_claim_is_rejected() -> None:
    token = encode_jwt({"sub": "a", "exp": int(time.time()) + 3600}, SECRET, alg="HS256")
    assert read_session_token(token, SECRET) is None


def test_a_token_with_a_non_string_sub_is_rejected() -> None:
    token = encode_jwt({"sub": 1, "pid": "me", "exp": int(time.time()) + 3600}, SECRET, alg="HS256")
    assert read_session_token(token, SECRET) is None


def test_rejecting_a_token_is_logged_without_leaking_the_token_or_secret(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # A misconfigured deployment or a caller bug must leave a trace -- see
    # finding 3 in the task-8 review. It must never leave the token or the
    # secret itself in that trace, since the token is a bearer credential.
    token = "not.a.token"
    with caplog.at_level(logging.DEBUG, logger="vouch.security"):
        assert read_session_token(token, SECRET) is None
    assert caplog.records, "expected the rejection to be logged"
    for record in caplog.records:
        assert token not in record.getMessage()
        assert SECRET not in record.getMessage()


def test_a_verify_password_failure_is_logged_as_a_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # verify_password itself never raises (see app.core.security's own
    # docstring on this), so this exercises the defensive backstop by forcing
    # a failure -- proving the except branch actually does something rather
    # than being silent dead code.
    import app.core.security as security

    def _boom(stored: str, candidate: str | bytes) -> bool:
        raise TypeError("simulated corruption")

    monkeypatch.setattr(security, "verify_password", _boom)
    with caplog.at_level(logging.WARNING, logger="vouch.security"):
        assert verify_account_password("anything", "corrupt-hash") is False
    assert any(r.levelno == logging.WARNING for r in caplog.records)
