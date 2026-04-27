"""add report versions

Revision ID: 20260427_0002
Revises: 20260427_0001
Create Date: 2026-04-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260427_0002"
down_revision: Union[str, None] = "20260427_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("operational_reports", sa.Column("report_version", sa.Integer(), nullable=False, server_default="1"))


def downgrade() -> None:
    op.drop_column("operational_reports", "report_version")
