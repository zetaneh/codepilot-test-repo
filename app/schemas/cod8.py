"""
Pydantic schemas for the COD-8 feature.

Provides request/response models with strict field validation,
extra-field rejection, and consistent error response shapes.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class Cod8Create(BaseModel):
    """Schema for creating a new COD-8 resource.

    Required fields
    ---------------
    title : str
        Human-readable title.  Maximum 200 characters.
    owner_id : int
        Identifier of the owning user (must be a positive integer).

    Optional fields
    ---------------
    description : str | None
        Longer free-text description.  Maximum 1 000 characters.
    priority : str
        One of ``"LOW"``, ``"MEDIUM"``, or ``"HIGH"`` (default ``"MEDIUM"``).
    tags : list[str]
        Arbitrary string tags.  Each tag is at most 50 characters; the list
        may contain at most 20 items.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Human-readable title (1–200 characters).",
        examples=["My first COD-8 item"],
    )
    owner_id: int = Field(
        ...,
        gt=0,
        description="Identifier of the owning user (positive integer).",
        examples=[42],
    )
    description: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Optional longer description (up to 1 000 characters).",
        examples=["Detailed description of the COD-8 item."],
    )
    priority: str = Field(
        default="MEDIUM",
        pattern=r"^(LOW|MEDIUM|HIGH)$",
        description="Priority level: LOW, MEDIUM, or HIGH.",
        examples=["HIGH"],
    )
    tags: List[str] = Field(
        default_factory=list,
        max_length=20,
        description="Optional list of string tags (max 20 items, each ≤ 50 chars).",
        examples=[["urgent", "backend"]],
    )

    # Per-item tag length is validated via a field validator.
    from pydantic import field_validator

    @field_validator("tags", mode="before")
    @classmethod
    def validate_tag_lengths(cls, value: Any) -> Any:  # type: ignore[override]
        """Ensure every tag in the list is at most 50 characters."""
        if not isinstance(value, list):
            return value  # let Pydantic's type system report the real error
        for tag in value:
            if isinstance(tag, str) and len(tag) > 50:
                raise ValueError(
                    f"Each tag must be at most 50 characters; got {len(tag)!r} for {tag!r}."
                )
        return value


class Cod8Update(BaseModel):
    """Schema for partially updating an existing COD-8 resource.

    All fields are optional; only the supplied fields will be changed.
    Extra fields are rejected.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=200,
        description="Updated title (1–200 characters).",
        examples=["Updated title"],
    )
    description: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Updated description (up to 1 000 characters).",
    )
    priority: Optional[str] = Field(
        default=None,
        pattern=r"^(LOW|MEDIUM|HIGH)$",
        description="Updated priority: LOW, MEDIUM, or HIGH.",
    )
    tags: Optional[List[str]] = Field(
        default=None,
        max_length=20,
        description="Replacement list of tags (max 20 items, each ≤ 50 chars).",
    )
    is_active: Optional[bool] = Field(
        default=None,
        description="Set to false to soft-delete / deactivate the resource.",
    )

    from pydantic import field_validator as _fv

    @_fv("tags", mode="before")
    @classmethod
    def validate_tag_lengths(cls, value: Any) -> Any:  # type: ignore[override]
        """Ensure every tag in the list is at most 50 characters."""
        if value is None or not isinstance(value, list):
            return value
        for tag in value:
            if isinstance(tag, str) and len(tag) > 50:
                raise ValueError(
                    f"Each tag must be at most 50 characters; got {len(tag)!r} for {tag!r}."
                )
        return value


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class Cod8Response(BaseModel):
    """Schema returned from the API for a single COD-8 resource.

    Extra fields from the persistence layer are silently ignored so that the
    API surface remains stable.
    """

    model_config = ConfigDict(extra="ignore", from_attributes=True)

    id: int = Field(..., description="Unique identifier assigned by the server.", examples=[1])
    title: str = Field(..., description="Title of the COD-8 resource.", examples=["My COD-8 item"])
    owner_id: int = Field(..., description="Identifier of the owning user.", examples=[42])
    description: Optional[str] = Field(
        default=None, description="Optional description.", examples=[None]
    )
    priority: str = Field(
        default="MEDIUM",
        description="Priority level: LOW, MEDIUM, or HIGH.",
        examples=["MEDIUM"],
    )
    tags: List[str] = Field(
        default_factory=list,
        description="List of tags associated with this resource.",
        examples=[["backend"]],
    )
    is_active: bool = Field(
        default=True, description="Whether the resource is active.", examples=[True]
    )
    created_at: Optional[datetime] = Field(
        default=None, description="UTC timestamp when the resource was created."
    )
    updated_at: Optional[datetime] = Field(
        default=None, description="UTC timestamp of the last update."
    )


# ---------------------------------------------------------------------------
# Error response schema
# ---------------------------------------------------------------------------


class Cod8ErrorDetail(BaseModel):
    """A single validation or business-logic error detail item."""

    model_config = ConfigDict(extra="forbid")

    field: Optional[str] = Field(
        default=None,
        description="Dot-separated path to the offending field, or null for non-field errors.",
        examples=["title"],
    )
    message: str = Field(
        ...,
        description="Human-readable error message.",
        examples=["Title must not exceed 200 characters."],
    )
    code: Optional[str] = Field(
        default=None,
        description="Optional machine-readable error code.",
        examples=["max_length"],
    )


class Cod8ErrorResponse(BaseModel):
    """Consistent error envelope returned when a COD-8 request fails.

    Structure
    ---------
    error   : short machine-readable error type
    message : human-readable summary of what went wrong
    details : list of per-field or per-rule error items (may be empty)
    meta    : optional free-form dictionary for tracing / context data
    """

    model_config = ConfigDict(extra="forbid")

    error: str = Field(
        ...,
        description="Short machine-readable error type (e.g. 'validation_error', 'not_found').",
        examples=["validation_error"],
    )
    message: str = Field(
        ...,
        description="Human-readable summary of the error.",
        examples=["Request validation failed."],
    )
    details: List[Cod8ErrorDetail] = Field(
        default_factory=list,
        description="List of individual error detail items.",
    )
    meta: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional metadata (request ID, timestamp, etc.).",
        examples=[{"request_id": "abc-123"}],
    )
