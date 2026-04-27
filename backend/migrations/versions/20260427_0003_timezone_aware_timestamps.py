"""make timestamps timezone aware

Revision ID: 20260427_0003
Revises: 20260427_0002
Create Date: 2026-04-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260427_0003"
down_revision: Union[str, None] = "20260427_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TIMESTAMP_COLUMNS = {
    "system_metrics": ["created_at"],
    "access_logs": ["created_at"],
    "incidents": ["created_at", "updated_at"],
    "evidence_logs": ["created_at"],
    "operational_reports": ["created_at"],
    "approvals": ["created_at", "decided_at"],
    "audit_logs": ["created_at"],
}


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        return
    for table_name, column_names in TIMESTAMP_COLUMNS.items():
        for column_name in column_names:
            op.alter_column(
                table_name,
                column_name,
                existing_type=sa.DateTime(),
                type_=sa.DateTime(timezone=True),
                existing_nullable=column_name == "decided_at",
            )


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        return
    for table_name, column_names in TIMESTAMP_COLUMNS.items():
        for column_name in column_names:
            op.alter_column(
                table_name,
                column_name,
                existing_type=sa.DateTime(timezone=True),
                type_=sa.DateTime(),
                existing_nullable=column_name == "decided_at",
            )
