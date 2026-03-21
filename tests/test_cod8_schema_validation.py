"""
Tests for app/schemas/cod8.py  (test hook: test_cod8_schema_validation)
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.cod8 import (
    Cod8Create,
    Cod8ErrorDetail,
    Cod8ErrorResponse,
    Cod8Response,
    Cod8Update,
)


# ---------------------------------------------------------------------------
# Cod8Create
# ---------------------------------------------------------------------------


class TestCod8Create:
    def test_valid_minimal(self) -> None:
        obj = Cod8Create(title="Hello", owner_id=1)
        assert obj.title == "Hello"
        assert obj.owner_id == 1
        assert obj.priority == "MEDIUM"
        assert obj.tags == []
        assert obj.description is None

    def test_valid_full(self) -> None:
        obj = Cod8Create(
            title="T" * 200,
            owner_id=99,
            description="D" * 1000,
            priority="HIGH",
            tags=["a", "b"],
        )
        assert obj.priority == "HIGH"
        assert len(obj.tags) == 2

    def test_title_too_long(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            Cod8Create(title="x" * 201, owner_id=1)
        errors = exc_info.value.errors()
        assert any("title" in str(e["loc"]) for e in errors)

    def test_title_empty(self) -> None:
        with pytest.raises(ValidationError):
            Cod8Create(title="", owner_id=1)

    def test_owner_id_zero(self) -> None:
        with pytest.raises(ValidationError):
            Cod8Create(title="Valid", owner_id=0)

    def test_owner_id_negative(self) -> None:
        with pytest.raises(ValidationError):
            Cod8Create(title="Valid", owner_id=-5)

    def test_invalid_priority(self) -> None:
        with pytest.raises(ValidationError):
            Cod8Create(title="Valid", owner_id=1, priority="CRITICAL")

    def test_description_too_long(self) -> None:
        with pytest.raises(ValidationError):
            Cod8Create(title="Valid", owner_id=1, description="d" * 1001)

    def test_tag_too_long(self) -> None:
        with pytest.raises(ValidationError):
            Cod8Create(title="Valid", owner_id=1, tags=["x" * 51])

    def test_extra_field_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            Cod8Create(title="Valid", owner_id=1, unknown_field="oops")

    def test_title_stripped(self) -> None:
        obj = Cod8Create(title="  Hello  ", owner_id=1)
        assert obj.title == "Hello"


# ---------------------------------------------------------------------------
# Cod8Update
# ---------------------------------------------------------------------------


class TestCod8Update:
    def test_valid_empty_update(self) -> None:
        obj = Cod8Update()
        assert obj.title is None
        assert obj.description is None
        assert obj.priority is None
        assert obj.tags is None
        assert obj.is_active is None

    def test_valid_partial(self) -> None:
        obj = Cod8Update(title="New title", is_active=False)
        assert obj.title == "New title"
        assert obj.is_active is False

    def test_title_too_long(self) -> None:
        with pytest.raises(ValidationError):
            Cod8Update(title="x" * 201)

    def test_title_empty_string(self) -> None:
        with pytest.raises(ValidationError):
            Cod8Update(title="")

    def test_invalid_priority(self) -> None:
        with pytest.raises(ValidationError):
            Cod8Update(priority="URGENT")

    def test_tag_too_long(self) -> None:
        with pytest.raises(ValidationError):
            Cod8Update(tags=["y" * 51])

    def test_extra_field_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            Cod8Update(nonexistent="value")


# ---------------------------------------------------------------------------
# Cod8Response
# ---------------------------------------------------------------------------


class TestCod8Response:
    def test_valid_minimal(self) -> None:
        obj = Cod8Response(id=1, title="Test", owner_id=2)
        assert obj.id == 1
        assert obj.is_active is True
        assert obj.tags == []

    def test_extra_fields_ignored(self) -> None:
        # extra='ignore' — unknown keys must not cause an error
        obj = Cod8Response(id=1, title="Test", owner_id=2, _db_internal="secret")
        assert not hasattr(obj, "_db_internal")

    def test_from_dict_with_extra(self) -> None:
        data = {
            "id": 7,
            "title": "My item",
            "owner_id": 3,
            "extra_col": "ignored",
        }
        obj = Cod8Response(**data)
        assert obj.id == 7


# ---------------------------------------------------------------------------
# Cod8ErrorResponse / Cod8ErrorDetail
# ---------------------------------------------------------------------------


class TestCod8ErrorResponse:
    def test_valid_minimal(self) -> None:
        obj = Cod8ErrorResponse(error="not_found", message="Resource does not exist.")
        assert obj.error == "not_found"
        assert obj.details == []
        assert obj.meta is None

    def test_valid_with_details(self) -> None:
        detail = Cod8ErrorDetail(field="title", message="Too long.", code="max_length")
        obj = Cod8ErrorResponse(
            error="validation_error",
            message="Request validation failed.",
            details=[detail],
            meta={"request_id": "abc"},
        )
        assert len(obj.details) == 1
        assert obj.details[0].field == "title"
        assert obj.meta == {"request_id": "abc"}

    def test_error_detail_extra_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            Cod8ErrorDetail(message="Something", unknown="x")

    def test_error_response_extra_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            Cod8ErrorResponse(error="e", message="m", unexpected=True)

    def test_detail_optional_fields_default_none(self) -> None:
        detail = Cod8ErrorDetail(message="Generic error.")
        assert detail.field is None
        assert detail.code is None
