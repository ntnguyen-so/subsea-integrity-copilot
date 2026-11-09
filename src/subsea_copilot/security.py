"""Local operator authentication; signed scoped sessions and CSRF protection."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

COOKIE_NAME = "subsea_session"
SESSION_SECONDS = 8 * 60 * 60


class AuthenticationError(ValueError):
    pass


@dataclass(frozen=True)
class Principal:
    username: str
    csrf_token: str


class SessionManager:
    """Verify one local operator and issue signed, expiring, stateless session cookies.

    The cookie is authenticated, not encrypted. Database tenant/site scope comes
    from application settings, not a client-controlled session claim.
    """

    def __init__(self, operator_password: str) -> None:
        self._hasher = PasswordHasher()
        self._password_hash = self._hasher.hash(operator_password)
        self._signing_key = hashlib.sha256(
            ("subsea-session-v1:" + operator_password).encode("utf-8")
        ).digest()

    def login(self, username: str, password: str) -> tuple[str, Principal]:
        if username != "operator":
            raise AuthenticationError("Invalid username or password")
        try:
            self._hasher.verify(self._password_hash, password)
        except VerifyMismatchError as exc:
            raise AuthenticationError("Invalid username or password") from exc
        principal = Principal(username="operator", csrf_token=secrets.token_urlsafe(32))
        payload = json.dumps(
            {
                "username": principal.username,
                "csrf": principal.csrf_token,
                "expires": int(time.time()) + SESSION_SECONDS,
                "nonce": secrets.token_hex(16),
            },
            separators=(",", ":"),
        ).encode("utf-8")
        encoded = base64.urlsafe_b64encode(payload).decode("ascii")
        signature = hmac.new(self._signing_key, encoded.encode("ascii"), hashlib.sha256)
        return encoded + "." + signature.hexdigest(), principal

    def authenticate(self, cookie: str | None) -> Principal:
        """Verify signature before decoding/trusting the payload, then enforce expiry."""
        if not cookie or len(cookie) > 2048:
            raise AuthenticationError("Operator login required")
        try:
            encoded, supplied = cookie.split(".", maxsplit=1)
            expected = hmac.new(
                self._signing_key, encoded.encode("ascii"), hashlib.sha256
            ).hexdigest()
            if not hmac.compare_digest(supplied, expected):
                raise AuthenticationError("Invalid operator session")
            value = json.loads(base64.urlsafe_b64decode(encoded))
        except (ValueError, UnicodeError) as exc:
            raise AuthenticationError("Invalid operator session") from exc
        if (
            not isinstance(value, dict)
            or value.get("username") != "operator"
            or not isinstance(value.get("expires"), int)
            or value["expires"] < time.time()
            or not isinstance(value.get("csrf"), str)
        ):
            raise AuthenticationError("Expired or invalid operator session")
        return Principal(username="operator", csrf_token=value["csrf"])

    @staticmethod
    def check_csrf(principal: Principal, token: str | None) -> None:
        if not token or not hmac.compare_digest(token, principal.csrf_token):
            raise AuthenticationError("Valid CSRF token required")
