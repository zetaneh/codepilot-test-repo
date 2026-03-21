"""
Application configuration — reads settings from environment variables.

Import the module-level ``settings`` singleton for default values, or
instantiate ``Settings()`` directly inside tests to pick up patched env vars.
"""
import logging
import os

logger = logging.getLogger(__name__)


class Settings:
    """Typed application settings backed by environment variables."""

    def __init__(self) -> None:
        self.RATE_LIMIT_WINDOW_SECONDS: int = int(
            os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60")
        )
        self.RATE_LIMIT_MAX_REQUESTS: int = int(
            os.getenv("RATE_LIMIT_MAX_REQUESTS", "10")
        )
        logger.debug(
            "Settings loaded: RATE_LIMIT_WINDOW_SECONDS=%d RATE_LIMIT_MAX_REQUESTS=%d",
            self.RATE_LIMIT_WINDOW_SECONDS,
            self.RATE_LIMIT_MAX_REQUESTS,
        )


# Module-level singleton — other modules import this directly.
settings: Settings = Settings()
