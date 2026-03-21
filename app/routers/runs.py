"""
Runs router — CRUD endpoints for pipeline/test runs.
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class Run(BaseModel):
    """A single pipeline/test run record."""

    id: int
    name: str
    status: str = "pending"  # pending | running | success | failure
    org_id: str = "default"


class RunCreate(BaseModel):
    """Payload required to create a new run."""

    name: str
    org_id: str = "default"


class RunUpdate(BaseModel):
    """Partial update payload for a run."""

    name: Optional[str] = None
    status: Optional[str] = None


# ---------------------------------------------------------------------------
# In-memory store (mirrors the pattern used by todos/users)
# ---------------------------------------------------------------------------

_runs: dict[int, dict] = {}
_next_id: int = 1


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/", summary="List all runs", tags=["runs"])
def list_runs(org_id: Optional[str] = None, status: Optional[str] = None) -> list[dict]:
    """Return all runs, optionally filtered by org_id and/or status."""
    items = list(_runs.values())
    if org_id is not None:
        items = [r for r in items if r["org_id"] == org_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return items


@router.get("/{run_id}", summary="Get a single run", tags=["runs"])
def get_run(run_id: int) -> dict:
    """Return the run identified by *run_id* or 404."""
    run = _runs.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.post("/", status_code=201, summary="Create a run", tags=["runs"])
def create_run(data: RunCreate) -> dict:
    """Create and persist a new run, returning the created record."""
    global _next_id
    run = {
        "id": _next_id,
        "name": data.name,
        "status": "pending",
        "org_id": data.org_id,
    }
    _runs[_next_id] = run
    _next_id += 1
    logger.info("Created run id=%d name=%s org_id=%s", run["id"], run["name"], run["org_id"])
    return run


@router.patch("/{run_id}", summary="Update a run", tags=["runs"])
def update_run(run_id: int, data: RunUpdate) -> dict:
    """Partially update a run's name or status."""
    run = _runs.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if data.name is not None:
        run["name"] = data.name
    if data.status is not None:
        run["status"] = data.status
    return run


@router.delete("/{run_id}", status_code=204, summary="Delete a run", tags=["runs"])
def delete_run(run_id: int) -> None:
    """Delete the run identified by *run_id* or 404."""
    if run_id not in _runs:
        raise HTTPException(status_code=404, detail="Run not found")
    del _runs[run_id]
    logger.info("Deleted run id=%d", run_id)
