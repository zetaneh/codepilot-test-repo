"""
RateLimitMiddleware — optional belt-and-suspenders middleware for rate limiting.

This middleware enforces rate limiting at the ASGI layer for POST /api/runs/trigger.
It is NOT registered in main.py by default to avoid double-limiting alongside the
rate-limit dependency. To enable it as a standalone alternative, add:

    from app.middleware.rate_limit_middleware import RateLimitMiddleware
    app.add_middleware(RateLimitMiddleware)

to app/main.py, and remove the rate-limit dependency from the route handler.
"""

import logging
from typing import Callable, Awaitable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

# Target path and method for rate limiting
_RATE_LIMIT_PATH = "/api/runs/trigger"
_RATE_LIMIT_METHOD = "POST"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Starlette middleware that enforces rate limiting for POST /api/runs/trigger.

    For all other paths/methods the request passes through unchanged.
    When the rate limit is exceeded a 429 response is returned immediately
    with a Retry-After header indicating when the client may retry.

    Usage (opt-in, in main.py)::

        from app.middleware.rate_limit_middleware import RateLimitMiddleware
        app.add_middleware(RateLimitMiddleware)
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """
        Intercept requests and apply rate limiting to POST /api/runs/trigger.

        :param request: The incoming HTTP request.
        :param call_next: Callable that forwards the request to the next handler.
        :return: Either a 429 Response (rate limited) or the downstream Response.
        """
        if (
            request.method.upper() == _RATE_LIMIT_METHOD
            and request.url.path == _RATE_LIMIT_PATH
        ):
            try:
                from app.core.rate_limit import check_rate_limit  # local import to avoid circular deps

                allowed, retry_after = await check_rate_limit(request)

                if not allowed:
                    logger.warning(
                        "Rate limit exceeded for %s %s — retry_after=%s",
                        request.method,
                        request.url.path,
                        retry_after,
                    )
                    headers = {}
                    if retry_after is not None:
                        headers["Retry-After"] = str(retry_after)
                    return Response(
                        content="Rate limit exceeded. Please retry later.",
                        status_code=429,
                        media_type="text/plain",
                        headers=headers,
                    )

            except ImportError:
                logger.error(
                    "app.core.rate_limit is not available; "
                    "RateLimitMiddleware will pass the request through."
                )

        return await call_next(request)
