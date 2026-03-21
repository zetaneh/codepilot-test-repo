"""
FastAPI dependencies for common request context extraction.
"""
import logging
from typing import Optional

from fastapi import Request

logger = logging.getLogger(__name__)


def get_org_id(request: Request) -> Optional[str]:
    """Extract org_id from the request context.

    In production this would decode a JWT Bearer token; for this test repo
    context it reads the value from the ``X-Org-ID`` header as a stand-in.

    Returns:
        The org_id string if present and non-empty, otherwise ``None``.
    """
    org_id: Optional[str] = request.headers.get("X-Org-ID")
    if not org_id or not org_id.strip():
        logger.debug("X-Org-ID header absent or empty; returning None")
        return None
    return org_id.strip()


try:
    from app.core.redis import get_redis  # noqa: F401 — re-exported for convenience
except ImportError:  # redis module not present in this repo; skip silently
    pass
