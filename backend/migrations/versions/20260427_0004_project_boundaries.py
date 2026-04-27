"""add project boundaries

Revision ID: 20260427_0004
Revises: 20260427_0003
Create Date: 2026-04-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260427_0004"
down_revision: Union[str, None] = "20260427_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PROJECT_TABLES = [
    "system_metrics",
    "access_logs",
    "incidents",
    "evidence_logs",
    "operational_reports",
    "approvals",
    "audit_logs",
]


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.String(length=80), nullable=False),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute("INSERT INTO projects (id, display_name, created_at) VALUES ('default', 'default', CURRENT_TIMESTAMP)")
    for table_name in PROJECT_TABLES:
        op.add_column(table_name, sa.Column("project_id", sa.String(length=80), nullable=False, server_default="default"))
        op.create_index(op.f(f"ix_{table_name}_project_id"), table_name, ["project_id"], unique=False)


def downgrade() -> None:
    for table_name in reversed(PROJECT_TABLES):
        op.drop_index(op.f(f"ix_{table_name}_project_id"), table_name=table_name)
        op.drop_column(table_name, "project_id")
    op.drop_table("projects")
