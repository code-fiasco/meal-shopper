"""Runtime configuration loaded from environment variables."""

from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process settings. Environment variables override the defaults."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_port: int = 5373
    database_url: str = "sqlite:////data/app.db"
    app_auth_user: str = ""
    app_auth_password: str = ""
    app_timezone: str = Field(
        default="Europe/London",
        validation_alias=AliasChoices("APP_TIMEZONE", "TZ"),
    )
    app_env: str = "development"

    @property
    def zoneinfo(self) -> ZoneInfo:
        """Timezone used for dates and backup timestamps."""
        return ZoneInfo(self.app_timezone)


@lru_cache
def get_settings() -> Settings:
    """Return cached settings."""
    return Settings()
