"""
/trigger endpoint — used for rate-limit integration testing.
"""
from fastapi import APIRouter, Depends
from app.rate_limit import rate_limit_dependency

router = APIRouter()


@router.post("/trigger", status_code=200)
def trigger(deps: None = Depends(rate_limit_dependency)):
    """Simple endpoint protected by the rate-limit dependency."""
    return {"status": "triggered"}
