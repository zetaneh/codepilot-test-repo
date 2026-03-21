"""
COD-8 router — placeholder endpoints for the cod8 feature.
"""
from fastapi import APIRouter

router = APIRouter()


@router.get("/")
def cod8_root() -> dict:
    """Root endpoint for the cod8 router."""
    return {"message": "cod8 router is active"}
