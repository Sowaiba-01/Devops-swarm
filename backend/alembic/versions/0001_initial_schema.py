"""Initial schema: runs and agent_logs.

Revision ID: 0001
Revises:
Create Date: 2026-08-15

Replaces the previous `Base.metadata.create_all()` call on startup, which could
create a table but never alter one — so any schema change after the first deploy
either required dropping the database or silently diverged from the models.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("repo_owner", sa.String(length=100), nullable=False),
        sa.Column("repo_name", sa.String(length=100), nullable=False),
        sa.Column("issue_number", sa.Integer(), nullable=False),
        sa.Column("issue_title", sa.String(length=500), nullable=True),
        sa.Column("installation_id", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
        sa.Column("phase", sa.String(length=20), nullable=True),
        sa.Column("pr_url", sa.String(length=500), nullable=True),
        sa.Column("branch_name", sa.String(length=255), nullable=True),
        sa.Column("iteration_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tests_passed", sa.Boolean(), nullable=True),
        sa.Column("review_verdict", sa.String(length=20), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("iteration_count >= 0", name="ck_runs_iteration_count_non_negative"),
        sa.PrimaryKeyConstraint("id"),
    )
    # The dashboard's hot path is "newest first, optionally filtered by status".
    op.create_index("ix_runs_created_at_desc", "runs", ["created_at"])
    op.create_index("ix_runs_status_created_at", "runs", ["status", "created_at"])
    op.create_index("ix_runs_repo", "runs", ["repo_owner", "repo_name"])
    op.create_index("ix_runs_status", "runs", ["status"])

    op.create_table(
        "agent_logs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("agent", sa.String(length=30), nullable=False),
        sa.Column("log_type", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("extra", sa.Text(), nullable=True),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        # Deleting a run must take its logs with it.
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_logs_run_id", "agent_logs", ["run_id"])
    op.create_index("ix_agent_logs_run_id_seq", "agent_logs", ["run_id", "seq"])


def downgrade() -> None:
    op.drop_index("ix_agent_logs_run_id_seq", table_name="agent_logs")
    op.drop_index("ix_agent_logs_run_id", table_name="agent_logs")
    op.drop_table("agent_logs")
    op.drop_index("ix_runs_status", table_name="runs")
    op.drop_index("ix_runs_repo", table_name="runs")
    op.drop_index("ix_runs_status_created_at", table_name="runs")
    op.drop_index("ix_runs_created_at_desc", table_name="runs")
    op.drop_table("runs")
