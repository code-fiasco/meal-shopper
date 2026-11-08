"""Environment settings."""

import pytest

from app.config import get_settings


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("APP_PORT", "DATABASE_URL", "APP_TIMEZONE", "TZ", "APP_ENV"):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.app_port == 5373
    assert settings.app_auth_user == ""
    assert settings.app_auth_password == ""
    assert settings.database_url == "sqlite:////data/app.db"
    assert settings.app_timezone == "Europe/London"
    assert settings.app_env == "development"


def test_app_timezone_overrides_tz(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TZ", "UTC")
    monkeypatch.setenv("APP_TIMEZONE", "Europe/London")
    get_settings.cache_clear()
    assert get_settings().app_timezone == "Europe/London"


def test_tz_is_used_when_app_timezone_is_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_TIMEZONE", raising=False)
    monkeypatch.setenv("TZ", "Europe/Dublin")
    get_settings.cache_clear()
    assert get_settings().app_timezone == "Europe/Dublin"
