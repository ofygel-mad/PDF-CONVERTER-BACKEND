"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-04-05 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("session_id", sa.String(64), primary_key=True),
        sa.Column("parser_key", sa.String(128), nullable=False, index=True),
        sa.Column("source_filename", sa.String(512), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("payload", sa.JSON, nullable=False),
    )

    op.create_table(
        "preferences",
        sa.Column("parser_key", sa.String(128), primary_key=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("payload", sa.JSON, nullable=False),
    )

    op.create_table(
        "transformation_templates",
        sa.Column("template_id", sa.String(64), primary_key=True),
        sa.Column("parser_key", sa.String(128), nullable=False, index=True),
        sa.Column("name", sa.String(255), nullable=False, index=True),
        sa.Column("is_default", sa.Boolean, nullable=False, server_default="false"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("payload", sa.JSON, nullable=False),
    )

    op.create_table(
        "ocr_reviews",
        sa.Column("review_id", sa.String(64), primary_key=True),
        sa.Column("source_filename", sa.String(512), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("payload", sa.JSON, nullable=False),
    )

    op.create_table(
        "ocr_mapping_templates",
        sa.Column("template_id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, index=True),
        sa.Column(
            "parser_key",
            sa.String(128),
            nullable=False,
            server_default="ocr_scanned_statement",
        ),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("status", sa.String(64), nullable=False, server_default="active"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("payload", sa.JSON, nullable=False),
    )

    op.create_table(
        "jobs",
        sa.Column("job_id", sa.String(64), primary_key=True),
        sa.Column("job_type", sa.String(64), nullable=False, index=True),
        sa.Column("status", sa.String(32), nullable=False, index=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("source_filename", sa.String(512), nullable=True),
        sa.Column("session_id", sa.String(64), nullable=True),
        sa.Column("review_id", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("payload", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("result_payload", sa.JSON, nullable=True),
    )

    op.create_table(
        "correction_memory",
        sa.Column("correction_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("parser_key", sa.String(128), nullable=False, index=True),
        sa.Column("field_name", sa.String(128), nullable=False, index=True),
        sa.Column("original_value", sa.String(512), nullable=False),
        sa.Column("corrected_value", sa.String(512), nullable=False),
        sa.Column("frequency", sa.Integer, nullable=False, server_default="1"),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "onboarding_projects",
        sa.Column("project_id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("bank_name", sa.String(255), nullable=False, index=True),
        sa.Column("status", sa.String(64), nullable=False, server_default="draft"),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "onboarding_samples",
        sa.Column("sample_id", sa.String(64), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(64),
            sa.ForeignKey("onboarding_projects.project_id"),
            nullable=False,
        ),
        sa.Column("source_filename", sa.String(512), nullable=False),
        sa.Column("review_id", sa.String(64), nullable=True),
        sa.Column("session_id", sa.String(64), nullable=True),
        sa.Column("status", sa.String(64), nullable=False, server_default="captured"),
        sa.Column("payload", sa.JSON, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("onboarding_samples")
    op.drop_table("onboarding_projects")
    op.drop_table("correction_memory")
    op.drop_table("jobs")
    op.drop_table("ocr_mapping_templates")
    op.drop_table("ocr_reviews")
    op.drop_table("transformation_templates")
    op.drop_table("preferences")
    op.drop_table("sessions")
