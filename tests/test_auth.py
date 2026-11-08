"""Optional Basic auth. The health check stays open for the container."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth import AuthConfigurationError, configured_credentials, credentials_match
from app.config import get_settings
from app.main import create_app


def test_open_when_credentials_are_unset(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("APP_AUTH_USER", raising=False)
    monkeypatch.delenv("APP_AUTH_PASSWORD", raising=False)
    get_settings.cache_clear()
    assert configured_credentials() is None
    assert client.get("/planner").status_code == 200


def test_basic_auth_rejects_a_wrong_password(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_AUTH_USER", "household")
    monkeypatch.setenv("APP_AUTH_PASSWORD", "correct horse")
    get_settings.cache_clear()
    with TestClient(create_app()) as client:
        assert client.get("/health").status_code == 200
        denied = client.get("/planner")
        assert denied.status_code == 401
        assert "Basic" in denied.headers["www-authenticate"]
        wrong = client.get("/planner", auth=("household", "nope"))
        assert wrong.status_code == 401
        allowed = client.get("/planner", auth=("household", "correct horse"))
        assert allowed.status_code == 200
    get_settings.cache_clear()


def test_comparison_checks_user_and_password() -> None:
    assert credentials_match(_header("household", "secret"), "household", "secret")
    assert not credentials_match(_header("household", "secret"), "household", "other")
    assert not credentials_match(_header("other", "secret"), "household", "secret")
    assert not credentials_match("", "household", "secret")


def test_one_sided_configuration_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_AUTH_USER", "household")
    monkeypatch.setenv("APP_AUTH_PASSWORD", "")
    get_settings.cache_clear()
    with pytest.raises(AuthConfigurationError):
        configured_credentials()
    get_settings.cache_clear()


def _header(user: str, password: str) -> str:
    import base64

    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return f"Basic {token}"
