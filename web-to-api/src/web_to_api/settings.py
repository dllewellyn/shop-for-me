from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="WEB_TO_API_",
        extra="ignore",
    )

    data_dir: Path = Path(".data")
    cache_ttl_seconds: int = Field(default=3600, ge=0)
    http_timeout_seconds: float = Field(default=20, gt=0)
    max_response_bytes: int = Field(default=2_000_000, ge=1024)
    user_agent: str = "web-to-api/0.1"
    logfire_include_content: bool = False
    pydantic_ai_model: str = Field(default="openai:gpt-5.2", validation_alias="PYDANTIC_AI_MODEL")

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def projects_dir(self) -> Path:
        return self.data_dir / "projects"


@lru_cache
def get_settings() -> Settings:
    return Settings()
