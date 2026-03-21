"""
Runs API routes — trigger endpoint with rate limiting.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Any, Dict

from app.dependencies import rate_limit_trigger

router = APIRouter()


class TriggerRequest(BaseModel):
    """Request body for POST /api/runs/trigger."""

    org_id: str
    run_name: str = ""
    metadata: Dict[str, Any] = {}


class TriggerResponse(BaseModel):
    """Response body for POST /api/runs/trigger."""

    status: str
    org_id: str
    message: str


@router.post(
    "/trigger",
    response_model=TriggerResponse,
    summary="Trigger a run",
    description="Trigger a new run for the given organisation. Subject to per-org rate limiting.",
    tags=["runs"],
)
async def trigger_run(
    body: TriggerRequest,
    _: None = Depends(rate_limit_trigger),
) -> TriggerResponse:
    """Trigger a run for *org_id*, enforcing the rate-limit dependency."""
    return TriggerResponse(
        status="accepted",
        org_id=body.org_id,
        message="Run trigger accepted.",
    )
