"""
Rate-limit middleware for FastAPI/Starlette.

Intercepts POST /api/runs/trigger requests and enforces per-org rate limits
via check_rate_limit().  Fails open when the backing store (Redis) is
unavailable so that a cache outage never blocks legitimate traffic.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional, Tuple

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rate-limit checker
# ---------------------------------------------------------------------------
# This function is intentionally thin and easy to mock in tests.  A real
# implementation would call Redis (e.g. via aioredis / redis-py async) and
# use a sliding-window or token-bucket algorithm.
#
# Return contract:
#   (True,  0)          — request is allowed
#   (False, retry_after) — request is denied; caller should wait `retry_after`
#                          seconds before retrying
# ---------------------------------------------------------------------------

def check_rate_limit(org_id: str) -> Tuple[bool, int]:
    """Check whether *org_id* has quota remaining.

    The default implementation always allows requests (no-op).  Wire in a
    real Redis-backed implementation by monkey-patching this function or
    by replacing the import in RateLimitMiddleware.

    Returns:
        A ``(allowed, retry_after)`` tuple where *allowed* is ``True`` when
        the request should proceed and *retry_after* is the number of seconds
        the client should wait before retrying (only meaningful when
        *allowed* is ``False``).

    Raises:
        Exception: Any exception is treated as a Redis/store outage and the
            middleware will *fail open* (allow the request).
    """
    # Default: allow everything.  Replace with real logic in production.
    return True, 0


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

class RateLimitMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that enforces per-org rate limits.

    Behaviour
    ---------
    * Only inspects ``POST /api/runs/trigger`` requests — all other paths
      pass through without any additional processing.
    * Reads the org identifier from the ``X-Org-ID`` request header.
    * Calls :func:`check_rate_limit` with the extracted *org_id*.
    * Returns **HTTP 429** with a ``Retry-After`` header when the limit is
      exceeded.
    * **Fails open**: if :func:`check_rate_limit` raises any exception (e.g.
      Redis is unreachable) the request is allowed through.
    """

    _TARGET_PATH: str = "/api/runs/trigger"
    _TARGET_METHOD: str = "POST"

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Middleware entry point called for every request."""
        if not self._is_target_request(request):
            return await call_next(request)

        org_id: Optional[str] = request.headers.get("X-Org-ID")

        if org_id is None:
            # No org header — pass through; downstream auth can reject it.
            logger.debug("RateLimitMiddleware: X-Org-ID header missing, skipping check.")
            return await call_next(request)

        try:
            allowed, retry_after = check_rate_limit(org_id)
        except Exception:  # noqa: BLE001
            # Fail open on any store / network error.
            logger.warning(
                "RateLimitMiddleware: check_rate_limit raised an exception for "
                "org_id=%r — failing open.",
                org_id,
                exc_info=True,
            )
            return await call_next(request)

        if not allowed:
            logger.info(
                "RateLimitMiddleware: rate limit exceeded for org_id=%r, "
                "retry_after=%d.",
                org_id,
                retry_after,
            )
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
                headers={"Retry-After": str(retry_after)},
            )

        return await call_next(request)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_target_request(self, request: Request) -> bool:
        """Return ``True`` only for ``POST /api/runs/trigger``."""
        return (
            request.method.upper() == self._TARGET_METHOD
            and request.url.path == self._TARGET_PATH
        )
