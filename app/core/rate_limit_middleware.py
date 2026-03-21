"""
Starlette/FastAPI middleware that enforces per-organisation rate limits using
the atomic Redis Lua logic in app.core.rate_limit.
"""
import logging

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.rate_limit import check_rate_limit
from app.core.redis import get_redis_client

logger = logging.getLogger(__name__)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Per-request rate-limit check.

    Reads the organisation identifier from the ``X-Org-ID`` request header
    (defaulting to ``"default"`` when absent) and delegates to
    :func:`app.core.rate_limit.check_rate_limit` for the actual enforcement.

    * Returns **HTTP 429** with a ``Retry-After`` header when the limit is
      exceeded.
    * Fails open — all requests are allowed through — when Redis is
      unavailable (consistent with ``check_rate_limit`` semantics).
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        org_id: str = request.headers.get("X-Org-ID", "default")
        redis_client = get_redis_client()

        result = await check_rate_limit(org_id, redis_client)

        if not result.allowed:
            logger.warning(
                "RateLimitMiddleware: rate limit exceeded org_id=%s current=%d limit=%d",
                org_id,
                result.current,
                result.limit,
            )
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
                headers={"Retry-After": str(result.retry_after)},
            )

        return await call_next(request)
