import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

_RATE_LIMITED_PATH = "/api/runs/trigger"
_RATE_LIMITED_METHOD = "POST"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Middleware that enforces per-org rate limits on POST /api/runs/trigger."""

    async def dispatch(self, request: Request, call_next):
        if request.method == _RATE_LIMITED_METHOD and request.url.path == _RATE_LIMITED_PATH:
            org_id: str | None = request.headers.get("X-Org-ID")

            if org_id is not None:
                try:
                    from app.core.config import settings
                    from app.core.redis import get_redis
                    from app.services.rate_limit_service import check_rate_limit

                    redis = await get_redis()
                    allowed, retry_after = await check_rate_limit(
                        redis=redis,
                        org_id=org_id,
                        limit=settings.RATE_LIMIT_MAX_REQUESTS,
                        window=settings.RATE_LIMIT_WINDOW_SECONDS,
                    )

                    if not allowed:
                        logger.warning(
                            "Rate limit exceeded for org_id=%s retry_after=%s",
                            org_id,
                            retry_after,
                        )
                        return JSONResponse(
                            content={"detail": "Rate limit exceeded"},
                            status_code=429,
                            headers={"Retry-After": str(retry_after)},
                        )
                except Exception:
                    logger.exception(
                        "Rate limit check failed for org_id=%s; allowing request through",
                        org_id,
                    )

        return await call_next(request)
