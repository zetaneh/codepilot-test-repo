"""
Starlette BaseHTTPMiddleware that enforces per-org rate limits on the
POST /api/runs/trigger endpoint via Redis-backed sliding-window counters.
"""
import json
import logging
from typing import Any, Callable, Coroutine, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from app.core.rate_limit import RateLimitResult, check_rate_limit

logger = logging.getLogger(__name__)

_TRIGGER_PATH = "/api/runs/trigger"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware that rate-limits POST requests to /api/runs/trigger by org_id.

    On any error (malformed body, missing org_id, Redis failure, etc.) the
    middleware fails open and passes the request through to the next handler.

    Constructor parameters
    ----------------------
    app:
        The ASGI application to wrap.
    redis_client:
        An optional async Redis client.  When omitted the middleware calls
        ``get_redis_client()`` from ``app.core.redis`` at construction time so
        that tests can inject a stub without touching global state.
    check_fn:
        Optional override for the rate-limit coroutine function, used in tests.
        Must have the same signature as ``check_rate_limit``.
    """

    def __init__(
        self,
        app: ASGIApp,
        redis_client: Optional[Any] = None,
        check_fn: Optional[
            Callable[[str, Optional[Any]], Coroutine[Any, Any, RateLimitResult]]
        ] = None,
    ) -> None:
        super().__init__(app)

        if redis_client is None:
            # Import here to allow the module to load even when redis is absent.
            from app.core.redis import get_redis_client

            self._redis_client: Optional[Any] = get_redis_client()
        else:
            self._redis_client = redis_client

        self._check_fn: Callable[
            [str, Optional[Any]], Coroutine[Any, Any, RateLimitResult]
        ] = check_fn if check_fn is not None else check_rate_limit

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        # Only enforce on POST /api/runs/trigger — pass everything else through.
        if request.method != "POST" or request.url.path != _TRIGGER_PATH:
            return await call_next(request)

        # Read body up-front; BaseHTTPMiddleware requires this before call_next.
        try:
            raw_body: bytes = await request.body()
        except Exception as exc:
            logger.warning(
                "RateLimitMiddleware: failed to read request body: %s; failing open", exc
            )
            return await call_next(request)

        # Parse org_id from JSON body — fail open on any parse error.
        org_id: Optional[str] = None
        try:
            payload = json.loads(raw_body)
            org_id = payload.get("org_id")
        except Exception as exc:
            logger.warning(
                "RateLimitMiddleware: could not parse JSON body: %s; failing open", exc
            )
            return await call_next(request)

        if not org_id:
            logger.debug(
                "RateLimitMiddleware: org_id missing or empty in request body; failing open"
            )
            return await call_next(request)

        # Perform the rate-limit check — fail open on any unexpected exception.
        try:
            result: RateLimitResult = await self._check_fn(org_id, self._redis_client)
        except Exception as exc:
            logger.error(
                "RateLimitMiddleware: check_rate_limit raised for org_id=%s: %s; failing open",
                org_id,
                exc,
            )
            return await call_next(request)

        if not result.allowed:
            logger.info(
                "RateLimitMiddleware: rate limit exceeded for org_id=%s "
                "(current=%d, limit=%d, retry_after=%d)",
                org_id,
                result.current,
                result.limit,
                result.retry_after,
            )
            return JSONResponse(
                content={"error": "rate_limit_exceeded", "retry_after": result.retry_after},
                status_code=429,
                headers={"Retry-After": str(result.retry_after)},
            )

        return await call_next(request)
