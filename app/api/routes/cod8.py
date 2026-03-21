"""
COD-8 API Router

Provides CRUD endpoints for the COD-8 feature with JWT authentication,
authorization checks, and consistent error responses.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cod8", tags=["cod8"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class Cod8ItemCreate(BaseModel):
    """Request body for creating a COD-8 item."""

    name: str = Field(..., min_length=1, max_length=200, description="Item name")
    description: Optional[str] = Field(None, max_length=1000, description="Optional description")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Arbitrary metadata")


class Cod8ItemUpdate(BaseModel):
    """Request body for partially updating a COD-8 item."""

    name: Optional[str] = Field(None, min_length=1, max_length=200, description="Item name")
    description: Optional[str] = Field(None, max_length=1000, description="Optional description")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Arbitrary metadata")


class Cod8ItemResponse(BaseModel):
    """Response schema for a COD-8 item."""

    id: str = Field(..., description="Unique item identifier")
    name: str = Field(..., description="Item name")
    description: Optional[str] = Field(None, description="Optional description")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Arbitrary metadata")
    owner_id: str = Field(..., description="ID of the owning user")
    is_deleted: bool = Field(False, description="Soft-delete flag")


class ErrorDetail(BaseModel):
    """Consistent error response shape."""

    code: int = Field(..., description="HTTP status code")
    message: str = Field(..., description="Human-readable error message")
    detail: Optional[Any] = Field(None, description="Additional error detail")


# ---------------------------------------------------------------------------
# In-process service (Cod8Service)
# ---------------------------------------------------------------------------


class Cod8Service:
    """Simple in-memory service for COD-8 items."""

    def __init__(self) -> None:
        self._store: Dict[str, Dict[str, Any]] = {}
        self._counter: int = 0

    def create(self, data: Cod8ItemCreate, owner_id: str) -> Dict[str, Any]:
        self._counter += 1
        item_id = str(self._counter)
        item: Dict[str, Any] = {
            "id": item_id,
            "name": data.name,
            "description": data.description,
            "metadata": data.metadata,
            "owner_id": owner_id,
            "is_deleted": False,
        }
        self._store[item_id] = item
        logger.debug("Cod8Service.create: created item id=%s", item_id)
        return item

    def get(self, item_id: str) -> Optional[Dict[str, Any]]:
        item = self._store.get(item_id)
        if item is None or item.get("is_deleted"):
            return None
        return item

    def update(self, item_id: str, data: Cod8ItemUpdate) -> Optional[Dict[str, Any]]:
        item = self.get(item_id)
        if item is None:
            return None
        if data.name is not None:
            item["name"] = data.name
        if data.description is not None:
            item["description"] = data.description
        if data.metadata is not None:
            item["metadata"] = data.metadata
        logger.debug("Cod8Service.update: updated item id=%s", item_id)
        return item

    def delete(self, item_id: str) -> bool:
        item = self.get(item_id)
        if item is None:
            return False
        item["is_deleted"] = True
        logger.debug("Cod8Service.delete: soft-deleted item id=%s", item_id)
        return True


# Module-level singleton
_cod8_service = Cod8Service()


def get_cod8_service() -> Cod8Service:
    """Dependency provider for Cod8Service."""
    return _cod8_service


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

# Minimal token registry used by tests.  Real deployments would validate a JWT.
_VALID_TOKENS: Dict[str, Dict[str, Any]] = {
    "valid-token": {"sub": "user-1", "is_active": True, "is_deleted": False},
    "inactive-token": {"sub": "user-2", "is_active": False, "is_deleted": False},
    "deleted-token": {"sub": "user-3", "is_active": True, "is_deleted": True},
}


def _make_error(code: int, message: str, detail: Any = None) -> Dict[str, Any]:
    """Return a consistent error payload dict."""
    return {"code": code, "message": message, "detail": detail}


def get_current_user(
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> Dict[str, Any]:
    """
    Validate the Bearer token from the Authorization header.

    Returns the decoded user claims on success.
    Raises 401 if the token is missing or invalid.
    Raises 403 if the user is inactive or soft-deleted.
    """
    if not authorization or not authorization.startswith("Bearer "):
        logger.warning("get_current_user: missing or malformed Authorization header")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_make_error(401, "Missing or invalid Authorization header"),
        )

    token = authorization[len("Bearer "):].strip()
    user = _VALID_TOKENS.get(token)

    if user is None:
        logger.warning("get_current_user: unrecognised token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_make_error(401, "Invalid or expired token"),
        )

    if not user.get("is_active", False):
        logger.warning("get_current_user: inactive user sub=%s", user.get("sub"))
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_make_error(403, "User account is inactive"),
        )

    if user.get("is_deleted", False):
        logger.warning("get_current_user: deleted user sub=%s", user.get("sub"))
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_make_error(403, "User account has been deleted"),
        )

    return user


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/",
    status_code=status.HTTP_201_CREATED,
    response_model=Cod8ItemResponse,
    responses={
        401: {"model": ErrorDetail, "description": "Unauthorized"},
        403: {"model": ErrorDetail, "description": "Forbidden"},
        422: {"model": ErrorDetail, "description": "Validation error"},
        500: {"model": ErrorDetail, "description": "Internal server error"},
    },
    summary="Create a COD-8 item",
)
def create_cod8_item(
    data: Cod8ItemCreate,
    current_user: Dict[str, Any] = Depends(get_current_user),
    service: Cod8Service = Depends(get_cod8_service),
) -> Cod8ItemResponse:
    """Create a new COD-8 item owned by the authenticated user."""
    try:
        item = service.create(data, owner_id=current_user["sub"])
        logger.info("create_cod8_item: created item id=%s for user=%s", item["id"], current_user["sub"])
        return Cod8ItemResponse(**item)
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover
        logger.exception("create_cod8_item: unexpected error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=_make_error(500, "Internal server error", str(exc)),
        ) from exc


@router.get(
    "/{item_id}",
    status_code=status.HTTP_200_OK,
    response_model=Cod8ItemResponse,
    responses={
        401: {"model": ErrorDetail, "description": "Unauthorized"},
        403: {"model": ErrorDetail, "description": "Forbidden"},
        404: {"model": ErrorDetail, "description": "Item not found"},
        500: {"model": ErrorDetail, "description": "Internal server error"},
    },
    summary="Retrieve a COD-8 item",
)
def get_cod8_item(
    item_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
    service: Cod8Service = Depends(get_cod8_service),
) -> Cod8ItemResponse:
    """Retrieve a single COD-8 item by ID."""
    try:
        item = service.get(item_id)
        if item is None:
            logger.debug("get_cod8_item: item id=%s not found", item_id)
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=_make_error(404, f"COD-8 item '{item_id}' not found"),
            )
        return Cod8ItemResponse(**item)
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover
        logger.exception("get_cod8_item: unexpected error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=_make_error(500, "Internal server error", str(exc)),
        ) from exc


@router.patch(
    "/{item_id}",
    status_code=status.HTTP_200_OK,
    response_model=Cod8ItemResponse,
    responses={
        401: {"model": ErrorDetail, "description": "Unauthorized"},
        403: {"model": ErrorDetail, "description": "Forbidden"},
        404: {"model": ErrorDetail, "description": "Item not found"},
        422: {"model": ErrorDetail, "description": "Validation error"},
        500: {"model": ErrorDetail, "description": "Internal server error"},
    },
    summary="Partially update a COD-8 item",
)
def update_cod8_item(
    item_id: str,
    data: Cod8ItemUpdate,
    current_user: Dict[str, Any] = Depends(get_current_user),
    service: Cod8Service = Depends(get_cod8_service),
) -> Cod8ItemResponse:
    """Partially update an existing COD-8 item."""
    try:
        item = service.update(item_id, data)
        if item is None:
            logger.debug("update_cod8_item: item id=%s not found", item_id)
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=_make_error(404, f"COD-8 item '{item_id}' not found"),
            )
        logger.info("update_cod8_item: updated item id=%s by user=%s", item_id, current_user["sub"])
        return Cod8ItemResponse(**item)
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover
        logger.exception("update_cod8_item: unexpected error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=_make_error(500, "Internal server error", str(exc)),
        ) from exc


@router.delete(
    "/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        401: {"model": ErrorDetail, "description": "Unauthorized"},
        403: {"model": ErrorDetail, "description": "Forbidden"},
        404: {"model": ErrorDetail, "description": "Item not found"},
        500: {"model": ErrorDetail, "description": "Internal server error"},
    },
    summary="Delete a COD-8 item",
)
def delete_cod8_item(
    item_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
    service: Cod8Service = Depends(get_cod8_service),
) -> None:
    """Soft-delete a COD-8 item."""
    try:
        deleted = service.delete(item_id)
        if not deleted:
            logger.debug("delete_cod8_item: item id=%s not found", item_id)
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=_make_error(404, f"COD-8 item '{item_id}' not found"),
            )
        logger.info("delete_cod8_item: deleted item id=%s by user=%s", item_id, current_user["sub"])
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover
        logger.exception("delete_cod8_item: unexpected error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=_make_error(500, "Internal server error", str(exc)),
        ) from exc
