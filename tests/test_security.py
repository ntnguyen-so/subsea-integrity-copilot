"""Check local session signatures, restart compatibility, credentials and CSRF rejection."""

import pytest

from subsea_copilot.security import AuthenticationError, SessionManager


def test_signed_session_survives_restart_without_allowing_tampering() -> None:
    original = SessionManager("a-synthetic-long-random-test-password")
    cookie, principal = original.login("operator", "a-synthetic-long-random-test-password")
    restarted = SessionManager("a-synthetic-long-random-test-password")
    assert restarted.authenticate(cookie) == principal
    with pytest.raises(AuthenticationError):
        restarted.authenticate(cookie[:-1] + ("1" if cookie[-1] != "1" else "2"))


def test_session_requires_correct_credentials_and_csrf() -> None:
    sessions = SessionManager("synthetic-only-test-password")
    with pytest.raises(AuthenticationError):
        sessions.login("operator", "incorrect-password")
    with pytest.raises(AuthenticationError):
        sessions.login("someone-else", "synthetic-only-test-password")
    cookie, principal = sessions.login("operator", "synthetic-only-test-password")
    sessions.check_csrf(sessions.authenticate(cookie), principal.csrf_token)
    with pytest.raises(AuthenticationError):
        sessions.check_csrf(principal, None)
    with pytest.raises(AuthenticationError):
        sessions.check_csrf(principal, "unrelated-token")
