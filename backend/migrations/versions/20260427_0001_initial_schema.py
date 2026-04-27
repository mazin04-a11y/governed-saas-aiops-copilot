"""initial schema

Revision ID: 20260427_0001
Revises: None
Create Date: 2026-04-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260427_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "system_metrics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("service_name", sa.String(length=120), nullable=False),
        sa.Column("cpu_usage", sa.Float(), nullable=False),
        sa.Column("memory_usage", sa.Float(), nullable=False),
        sa.Column("response_time_ms", sa.Integer(), nullable=False),
        sa.Column("error_rate", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_system_metrics_service_name"), "system_metrics", ["service_name"], unique=False)

    op.create_table(
        "access_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=160), nullable=False),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("ip_address", sa.String(length=80), nullable=False),
        sa.Column("outcome", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_access_logs_ip_address"), "access_logs", ["ip_address"], unique=False)
    op.create_index(op.f("ix_access_logs_outcome"), "access_logs", ["outcome"], unique=False)
    op.create_index(op.f("ix_access_logs_username"), "access_logs", ["username"], unique=False)

    op.create_table(
        "incidents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("incident_type", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("severity", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("correlation_key", sa.String(length=240), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_incidents_correlation_key"), "incidents", ["correlation_key"], unique=True)
    op.create_index(op.f("ix_incidents_incident_type"), "incidents", ["incident_type"], unique=False)
    op.create_index(op.f("ix_incidents_severity"), "incidents", ["severity"], unique=False)
    op.create_index(op.f("ix_incidents_status"), "incidents", ["status"], unique=False)

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=120), nullable=False),
        sa.Column("actor", sa.String(length=120), nullable=False),
        sa.Column("entity_type", sa.String(length=120), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_audit_logs_event_type"), "audit_logs", ["event_type"], unique=False)

    op.create_table(
        "evidence_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("incident_id", sa.Integer(), nullable=True),
        sa.Column("evidence_type", sa.String(length=80), nullable=False),
        sa.Column("source_table", sa.String(length=80), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_evidence_logs_evidence_type"), "evidence_logs", ["evidence_type"], unique=False)
    op.create_index(op.f("ix_evidence_logs_incident_id"), "evidence_logs", ["incident_id"], unique=False)

    op.create_table(
        "operational_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("incident_id", sa.Integer(), nullable=False),
        sa.Column("model_name", sa.String(length=120), nullable=False),
        sa.Column("prompt_version", sa.String(length=120), nullable=False),
        sa.Column("schema_version", sa.String(length=120), nullable=False),
        sa.Column("raw_llm_output", sa.JSON(), nullable=False),
        sa.Column("parsed_json", sa.JSON(), nullable=False),
        sa.Column("validation_status", sa.String(length=80), nullable=False),
        sa.Column("human_approval_required", sa.Boolean(), nullable=False),
        sa.Column("human_approved", sa.Boolean(), nullable=True),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_operational_reports_incident_id"), "operational_reports", ["incident_id"], unique=False)
    op.create_index(op.f("ix_operational_reports_validation_status"), "operational_reports", ["validation_status"], unique=False)

    op.create_table(
        "approvals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("report_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("reviewer", sa.String(length=120), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["report_id"], ["operational_reports.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_approvals_report_id"), "approvals", ["report_id"], unique=False)
    op.create_index(op.f("ix_approvals_status"), "approvals", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_approvals_status"), table_name="approvals")
    op.drop_index(op.f("ix_approvals_report_id"), table_name="approvals")
    op.drop_table("approvals")
    op.drop_index(op.f("ix_operational_reports_validation_status"), table_name="operational_reports")
    op.drop_index(op.f("ix_operational_reports_incident_id"), table_name="operational_reports")
    op.drop_table("operational_reports")
    op.drop_index(op.f("ix_evidence_logs_incident_id"), table_name="evidence_logs")
    op.drop_index(op.f("ix_evidence_logs_evidence_type"), table_name="evidence_logs")
    op.drop_table("evidence_logs")
    op.drop_index(op.f("ix_audit_logs_event_type"), table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_index(op.f("ix_incidents_status"), table_name="incidents")
    op.drop_index(op.f("ix_incidents_severity"), table_name="incidents")
    op.drop_index(op.f("ix_incidents_incident_type"), table_name="incidents")
    op.drop_index(op.f("ix_incidents_correlation_key"), table_name="incidents")
    op.drop_table("incidents")
    op.drop_index(op.f("ix_access_logs_username"), table_name="access_logs")
    op.drop_index(op.f("ix_access_logs_outcome"), table_name="access_logs")
    op.drop_index(op.f("ix_access_logs_ip_address"), table_name="access_logs")
    op.drop_table("access_logs")
    op.drop_index(op.f("ix_system_metrics_service_name"), table_name="system_metrics")
    op.drop_table("system_metrics")

