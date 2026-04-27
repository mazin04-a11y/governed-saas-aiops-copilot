from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.api.dependencies import rate_limit, require_ingest_api_key
from app.core.database import get_session
from app.models.records import AccessLog, Approval, AuditLog, Incident, OperationalReport, SystemMetric
from app.schemas.records import AccessLogIn, ApprovalDecisionIn, IncidentOut, MetricIn, ReportRequest
from app.services.audit import audit
from app.services.detection import ingest_access_log, ingest_metric
from app.services.reporting import run_report_workflow

router = APIRouter()


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "governed-saas-aiops-copilot"}


@router.post("/metrics/ingest", dependencies=[Depends(rate_limit), Depends(require_ingest_api_key)])
def metrics_ingest(payload: MetricIn, session: Session = Depends(get_session)) -> dict:
    metric, incident = ingest_metric(session, payload)
    return {"metric_id": metric.id, "incident_id": incident.id if incident else None}


@router.post("/access-logs/ingest", dependencies=[Depends(rate_limit), Depends(require_ingest_api_key)])
def access_logs_ingest(payload: AccessLogIn, session: Session = Depends(get_session)) -> dict:
    access_log, incident = ingest_access_log(session, payload)
    return {"access_log_id": access_log.id, "incident_id": incident.id if incident else None}


@router.get("/metrics")
def list_metrics(session: Session = Depends(get_session)) -> list[dict]:
    rows = session.scalars(select(SystemMetric).order_by(desc(SystemMetric.created_at)).limit(100)).all()
    return [_row_dict(row) for row in rows]


@router.get("/access-logs")
def list_access_logs(session: Session = Depends(get_session)) -> list[dict]:
    rows = session.scalars(select(AccessLog).order_by(desc(AccessLog.created_at)).limit(100)).all()
    return [_row_dict(row) for row in rows]


@router.get("/incidents", response_model=list[IncidentOut])
def list_incidents(session: Session = Depends(get_session)):
    return session.scalars(select(Incident).order_by(desc(Incident.updated_at))).all()


@router.post("/incidents/{incident_id}/reports")
def create_report(incident_id: int, payload: ReportRequest | None = None, session: Session = Depends(get_session)) -> dict:
    try:
        report = run_report_workflow(session, incident_id, use_external_intel=payload.use_external_intel if payload else False)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.errors()) from exc
    return {"report_id": report.id, "human_approval_required": report.human_approval_required}


@router.get("/reports")
def list_reports(session: Session = Depends(get_session)) -> list[dict]:
    rows = session.scalars(select(OperationalReport).order_by(desc(OperationalReport.created_at))).all()
    return [_row_dict(row) for row in rows]


@router.get("/approvals")
def list_approvals(session: Session = Depends(get_session)) -> list[dict]:
    rows = session.scalars(select(Approval).order_by(desc(Approval.created_at))).all()
    return [_row_dict(row) for row in rows]


@router.post("/approvals/{approval_id}/decision")
def decide_approval(approval_id: int, payload: ApprovalDecisionIn, session: Session = Depends(get_session)) -> dict:
    approval = session.get(Approval, approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="approval not found")
    if approval.status != "pending":
        raise HTTPException(status_code=409, detail="approval already decided")
    report = session.get(OperationalReport, approval.report_id)
    approval.status = payload.status
    approval.reviewer = payload.reviewer
    approval.decision_reason = payload.decision_reason
    approval.decided_at = datetime.utcnow()
    if report:
        report.human_approved = payload.status == "approved"
    audit(
        session,
        f"approval_{payload.status}",
        payload.reviewer,
        "approval",
        approval.id,
        {"report_id": approval.report_id, "reason": payload.decision_reason},
    )
    session.commit()
    return {"approval_id": approval.id, "status": approval.status}


@router.get("/audit-logs")
def list_audit_logs(session: Session = Depends(get_session)) -> list[dict]:
    rows = session.scalars(select(AuditLog).order_by(desc(AuditLog.created_at)).limit(200)).all()
    return [_row_dict(row) for row in rows]


def _row_dict(row) -> dict:
    data = {column.name: getattr(row, column.name) for column in row.__table__.columns}
    for key, value in data.items():
        if hasattr(value, "isoformat"):
            data[key] = value.isoformat()
    return data
