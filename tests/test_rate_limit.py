"""
Tests for Redis fail-open behavior (rate-limit infrastructure).
"""
import os
from unittest.mock import patch, MagicMock


def test_redis_unavailable_fails_open():
    """
    When Redis is unreachable, get_redis_client() should return None
    rather than raising an exception (fail-open semantics).
    """
    # Simulate Redis raising an error on pool creation
    with patch.dict(os.environ, {"REDIS_URL": "redis://127.0.0.1:19999"}):
        with patch("app.core.redis._REDIS_AVAILABLE", True):
            with patch("app.core.redis.ConnectionPool") as mock_pool_cls:
                mock_pool_cls.from_url.side_effect = Exception(
                    "Connection refused to 127.0.0.1:19999"
                )
                from app.core.redis import get_redis_client
                import app.core.redis as redis_module
                original_pool = redis_module.ConnectionPool
                redis_module.ConnectionPool = mock_pool_cls
                try:
                    result = redis_module.get_redis_client()
                finally:
                    redis_module.ConnectionPool = original_pool

    assert result is None, "get_redis_client() must return None when Redis is unavailable"
