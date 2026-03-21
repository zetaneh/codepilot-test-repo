from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter()


class RunTriggerRequest(BaseModel):
    """Request body for triggering a run."""

    org_id: str = Field(..., min_length=1, max_length=256, description="Organisation identifier")


class RunTriggerResponse(BaseModel):
    """Response payload returned after a run is triggered."""

    status: str
    org_id: str


@router.post(
    "/trigger",
    response_model=RunTriggerResponse,
    summary="Trigger a run",
    description="Trigger a new run for the given organisation. Rate limiting is enforced by the middleware layer.",
)
def trigger_run(body: RunTriggerRequest) -> RunTriggerResponse:
    """Accept an org_id, validate it, and return a triggered status."""
    return RunTriggerResponse(status="triggered", org_id=body.org_id)
