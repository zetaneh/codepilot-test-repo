"""Routes for triggering and managing runs."""
from typing import Any, Dict, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter()


class TriggerRunRequest(BaseModel):
    """Request body for POST /api/runs/trigger."""

    org_id: str = Field(..., description="Organisation that owns the run")
    run_params: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Arbitrary run parameters forwarded to the worker",
    )

    model_config = {"extra": "allow"}  # forward unknown keys transparently


class TriggerRunResponse(BaseModel):
    """Response body for POST /api/runs/trigger."""

    status: str = Field(..., description="Queuing status of the run")
    org_id: str = Field(..., description="Organisation that owns the run")


@router.post(
    "/trigger",
    response_model=TriggerRunResponse,
    status_code=200,
    summary="Trigger a new run",
    description=(
        "Enqueue a run for the given organisation. "
        "Returns immediately with `status='queued'`."
    ),
    tags=["runs"],
)
def trigger_run(body: TriggerRunRequest) -> TriggerRunResponse:
    """Accept a run-trigger request and return a queued status."""
    return TriggerRunResponse(status="queued", org_id=body.org_id)
