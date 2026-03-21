import logging
from fastapi import Depends, HTTPException, Request
from app.core.rate_limit import check_rate_limit
from app.core.redis import get_redis_client

logger = logging.getLogger(__name__)


async def rate_limit_trigger(
    request: Request,
    redis=Depends(get_redis_client),
) -> None:
    """FastAPI dependency that enforces per-org rate limits.

    Extracts ``org_id`` from ``request.state`` (set by auth middleware) or
    falls back to the JSON request body.  Calls :func:`check_rate_limit` and
    raises :class:`~fastapi.HTTPException` 429 when the limit is exceeded.
    """
    org_id: str | None = None

    # 1. Try request.state first (populated by auth middleware)
    if hasattr(request.state, "org_id") and request.state.org_id is not None:
        org_id = str(request.state.org_id)
        logger.debug("rate_limit_trigger: org_id=%s from request.state", org_id)
    else:
        # 2. Fall back to JSON body
        try:
            body = await request.json()
            if isinstance(body, dict) and body.get("org_id") is not None:
                org_id = str(body["org_id"])
                logger.debug(
                    "rate_limit_trigger: org_id=%s from request body", org_id
                )
        except Exception:
            # Body may be absent or non-JSON — treat org_id as None
            pass

    if org_id is None:
        logger.debug(
            "rate_limit_trigger: no org_id found, skipping rate-limit check"
        )
        return

    result = await check_rate_limit(redis, org_id)
    allowed: bool = result.get("allowed", True)
    retry_after: int = result.get("retry_after", 0)

    if not allowed:
        logger.warning(
            "rate_limit_trigger: rate limit exceeded for org_id=%s retry_after=%s",
            org_id,
            retry_after,
        )
        raise HTTPException(
            status_code=429,
            headers={"Retry-After": str(retry_after)},
            detail="Rate limit exceeded",
        )
