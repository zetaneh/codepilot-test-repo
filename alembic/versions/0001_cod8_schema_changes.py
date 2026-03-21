"""cod8_schema_changes

Revision ID: 0001_cod8_schema_changes
Revises:
Create Date: 2024-01-01 00:00:00.000000

Creates the cod8_items table with soft-delete support.
This migration is idempotent: upgrade() checks for table existence
before creating, and downgrade() checks before dropping.
"""
from __future__ import annotations

import logging
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection
from sqlalchemy import inspect

# revision identifiers, used by Alembic
revision: str = "0001_cod8_schema_changes"
down_revision: Union[str, None] = None
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None

log = logging.getLogger(__name__)

TABLE_NAME = "cod8_items"


def _table_exists(connection: Connection) -> bool:
    """Return True if the cod8_items table already exists in the database."""
    inspector = inspect(connection)
    return TABLE_NAME in inspector.get_table_names()


def upgrade() -> None:
    """Create the cod8_items table if it does not already exist."""
    bind: Connection = op.get_bind()
    if _table_exists(bind):
        log.info(
            "Table '%s' already exists — skipping creation (idempotent upgrade).",
            TABLE_NAME,
        )
        return

    op.create_table(
        TABLE_NAME,
        # Primary key
        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True,
            autoincrement=True,
            nullable=False,
        ),
        # Core fields
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(50), nullable=True),
        # Foreign key to users table
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        # Timestamps
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=False),
            nullable=True,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=False),
            nullable=True,
            server_default=sa.text("NOW()"),
        ),
        # Soft-delete support
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=False), nullable=True),
    )
    log.info("Table '%s' created successfully.", TABLE_NAME)


def downgrade() -> None:
    """Drop the cod8_items table if it exists."""
    bind: Connection = op.get_bind()
    if not _table_exists(bind):
        log.info(
            "Table '%s' does not exist — skipping drop (idempotent downgrade).",
            TABLE_NAME,
        )
        return

    op.drop_table(TABLE_NAME)
    log.info("Table '%s' dropped successfully.", TABLE_NAME)
