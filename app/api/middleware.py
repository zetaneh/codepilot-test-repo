"""Rate limiting middleware for the API."""
import time
from collections import defaultdict
from typing import Callable, Dict, List

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple sliding-window rate limiter keyed by client IP."""

    def __init__(
        self,
        app: Callable,
        max_requests: int = 100,
        window_seconds: int = 60,
    ) -> None:
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._counts: Dict[str, List[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next: Callable) -> JSONResponse:
        client_ip: str = (
            request.client.host if request.client else "unknown"
        )
        now = time.time()
        window_start = now - self.window_seconds

        # Prune timestamps outside the current window
        self._counts[client_ip] = [
            t for t in self._counts[client_ip] if t > window_start
        ]

        if len(self._counts[client_ip]) >= self.max_requests:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
            )

        self._counts[client_ip].append(now)
        return await call_next(request)
