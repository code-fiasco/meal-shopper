"""Runtime configuration loaded from environment variables."""

from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process settings. Environment variables override the defaults."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_port: int = 8000
    database_url: str = "sqlite:////data/app.db"
    app_timezone: str = Field(
        default="Europe/London",
        validation_alias=AliasChoices("APP_TIMEZONE", "TZ"),
    )
    app_env: str = "development"


@lru_cache
def get_settings() -> Settings:
    """Return cached settings."""
    return Settings()
