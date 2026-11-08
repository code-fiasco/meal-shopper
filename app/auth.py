"""Optional HTTP Basic authentication. Unset credentials leave the app open."""

import hashlib
import hmac
from base64 import b64decode
from collections.abc import Awaitable, Callable

from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import get_settings

_REALM = 'Basic realm="Meal Shopper", charset="UTF-8"'


class AuthConfigurationError(RuntimeError):
    """Raised when only one of the auth environment variables is set."""


def configured_credentials() -> tuple[str, str] | None:
    """Return the configured user and password, or None when auth is off."""
    settings = get_settings()
    user = settings.app_auth_user.strip()
    password = settings.app_auth_password
    if not user and not password:
        return None
    if not user or not password:
        raise AuthConfigurationError(
            "Set both APP_AUTH_USER and APP_AUTH_PASSWORD, or leave both unset."
        )
    return user, password


def credentials_match(header: str, user: str, password: str) -> bool:
    """Compare a Basic header with the expected credentials in constant time."""
    provided_user, provided_password = _decode_basic(header)
    user_ok = _digest_equal(provided_user, user)
    password_ok = _digest_equal(provided_password, password)
    return user_ok and password_ok


class BasicAuthMiddleware:
    """Ask for Basic credentials when APP_AUTH_USER and APP_AUTH_PASSWORD are set."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") == "/health":
            await self.app(scope, receive, send)
            return
        pair = configured_credentials()
        if pair is None:
            await self.app(scope, receive, send)
            return
        if credentials_match(_authorization(scope), pair[0], pair[1]):
            await self.app(scope, receive, send)
            return
        response = Response(
            "Authentication required",
            status_code=401,
            headers={"WWW-Authenticate": _REALM},
        )
        await response(scope, receive, send)


def install_auth(app: ASGIApp) -> Callable[[Scope, Receive, Send], Awaitable[None]]:
    """Fail fast on a half-set configuration, then require credentials."""
    configured_credentials()
    return BasicAuthMiddleware(app)


def _authorization(scope: Scope) -> str:
    for key, value in scope.get("headers", []):
        if key.lower() == b"authorization":
            return value.decode("latin-1")
    return ""


def _decode_basic(header: str) -> tuple[str, str]:
    scheme, _, encoded = header.partition(" ")
    if scheme.lower() != "basic" or not encoded:
        return "", ""
    try:
        decoded = b64decode(encoded, validate=True).decode()
    except (ValueError, UnicodeError):
        return "", ""
    user, separator, password = decoded.partition(":")
    if not separator:
        return "", ""
    return user, password


def _digest_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(
        hashlib.sha256(left.encode()).digest(),
        hashlib.sha256(right.encode()).digest(),
    )
