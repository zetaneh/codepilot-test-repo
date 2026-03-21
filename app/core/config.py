"""Central configuration for the Todo API application.

All settings can be overridden via environment variables.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings with environment variable override support."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # COD-8: Redis cache TTL in seconds
    COD8_REDIS_TTL_SECONDS: int = 300

    # COD-8: Claude agent HTTP timeout in seconds
    COD8_CLAUDE_TIMEOUT_SECONDS: int = 30

    # COD-8: Maximum number of retries for Claude agent calls
    COD8_CLAUDE_MAX_RETRIES: int = 3

    # COD-8: Exponential backoff factor between retries
    COD8_CLAUDE_BACKOFF_FACTOR: float = 1.5


settings = Settings()
