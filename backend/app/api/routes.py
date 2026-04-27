import csv
import hmac
import io

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.api.dependencies import create_operator_token, get_project_id, rate_limit, require_ingest_api_key, require_operator_session
from app.core.config import get_settings
from app.core.database import get_session
from app.core.time import utc_now
from app.models.records import AccessLog, Approval, AuditLog, EvidenceLog, Incident, OperationalReport, Project, SystemMetric
from app.schemas.records import (
    AccessLogIn,
    ApprovalDecisionIn,
    IncidentOut,
    IncidentStatusUpdate,
    MetricIn,
    OperatorLoginIn,
    OperatorSessionOut,
    ReportRequest,
)
from app.services.audit import audit
from app.services.detection import ingest_access_log, ingest_metric
from app.services.reporting import run_report_workflow

router = APIRouter()
operator_auth = [Depends(require_operator_session)]


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "governed-saas-aiops-copilot"}


@router.post("/auth/login", response_model=OperatorSessionOut, dependencies=[Depends(rate_limit)])
def operator_login(payload: OperatorLoginIn) -> OperatorSessionOut:
    settings = get_settings()
    if not settings.operator_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="operator password authentication is not configured")
    valid_username = hmac.compare_digest(payload.username, settings.operator_username)
    valid_password = hmac.compare_digest(payload.password, settings.operator_password)
    if not valid_username or not valid_password:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid operator credentials")
    return OperatorSessionOut(
        access_token=create_operator_token(payload.username),
        expires_in=settings.operator_session_ttl_seconds,
        username=payload.username,
    )


@router.post("/metrics/ingest", dependencies=[Depends(rate_limit), Depends(require_ingest_api_key)])
def metrics_ingest(payload: MetricIn, project_id: str = Depends(get_project_id), session: Session = Depends(get_session)) -> dict:
    metric, incident = ingest_metric(session, payload, project_id)
    return {"metric_id": metric.id, "incident_id": incident.id if incident else None}


@router.post("/access-logs/ingest", dependencies=[Depends(rate_limit), Depends(require_ingest_api_key)])
def access_logs_ingest(payload: AccessLogIn, project_id: str = Depends(get_project_id), session: Session = Depends(get_session)) -> dict:
    access_log, incident = ingest_access_log(session, payload, project_id)
    return {"access_log_id": access_log.id, "incident_id": incident.id if incident else None}


@router.get("/projects", dependencies=operator_auth)
def list_projects(session: Session = Depends(get_session)) -> list[dict]:
    rows = session.scalars(select(Project).order_by(Project.id)).all()
    if not rows:
        return [{"id": "default", "display_name": "default"}]
    return [_row_dict(row) for row in rows]


@router.get("/metrics", dependencies=operator_auth)
def list_metrics(project_id: str = Depends(get_project_id), session: Session = Depends(get_session)) -> list[dict]:
    rows = session.scalars(select(SystemMetric).where(SystemMetric.project_id == project_id).order_by(desc(SystemMetric.created_at)).limit(100)).all()
    return [_row_dict(row) for row in rows]


@router.get("/access-logs", dependencies=operator_auth)
def list_access_logs(project_id: str = Depends(get_project_id), session: Session = Depends(get_session)) -> list[dict]:
    rows = session.scalars(select(AccessLog).where(AccessLog.project_id == project_id).order_by(desc(AccessLog.created_at)).limit(100)).all()
    return [_row_dict(row) for row in rows]


@router.get("/incidents", response_model=list[IncidentOut], dependencies=operator_auth)
def list_incidents(project_id: str = Depends(get_project_id), session: Session = Depends(get_session)):
    return session.scalars(select(Incident).where(Incident.project_id == project_id).order_by(desc(Incident.updated_at))).all()


@router.get("/incidents/{incident_id}", dependencies=operator_auth)
def get_incident(incident_id: int, project_id: str = Depends(get_project_id), session: Session = Depends(get_session)) -> dict:
    incident = session.get(Incident, incident_id)
    if not incident or incident.project_id != project_id:
        raise HTTPException(status_code=404, detail="incident not found")
    return _row_dict(incident)


@router.get("/incidents/{incident_id}/evidence", dependencies=operator_auth)
def list_incident_evidence(incident_id: int, project_id: str = Depends(get_project_id), session: Session = Depends(get_session)) -> list[dict]:
    incident = session.get(Incident, incident_id)
    if not incident or incident.project_id != project_id:
        raise HTTPException(status_code=404, detail="incident not found")
    if not incident.evidence_ids:
        return []
    rows = session.scalars(
        select(EvidenceLog).where(EvidenceLog.project_id == project_id, EvidenceLog.id.in_(incident.evidence_ids)).order_by(desc(EvidenceLog.created_at))
    ).all()
    return [_row_dict(row) for row in rows]


@router.get("/incidents/{incident_id}/timeline", dependencies=operator_auth)
def get_incident_timeline(incident_id: int, project_id: str = Depends(get_project_id), session: Session = Depends(get_session)) -> list[dict]:
    incident = session.get(Incident, incident_id)
    if not incident or incident.project_id != project_id:
        raise HTTPException(status_code=404, detail="incident not found")

    events = [
        {
            "timestamp": incident.created_at.isoformat(),
            "event_type": "incident_created",
            "title": incident.title,
            "details": {"severity": incident.severity, "correlation_key": incident.correlation_key},
        }
    ]
    evidence_rows = session.scalars(select(EvidenceLog).where(EvidenceLog.project_id == project_id, EvidenceLog.incident_id == incident_id)).all()
    for row in evidence_rows:
        events.append(
            {
                "timestamp": row.created_at.isoformat(),
                "event_type": f"evidence:{row.evidence_type}",
                "title": row.summary,
                "details": row.payload,
            }
        )

    reports = session.scalars(select(OperationalReport).where(OperationalReport.project_id == project_id, OperationalReport.incident_id == incident_id)).all()
    report_ids = [report.id for report in reports]
    for report in reports:
        events.append(
            {
                "timestamp": report.created_at.isoformat(),
                "event_type": "report_saved",
                "title": f"Report v{report.report_version} saved",
                "details": {
                    "report_id": report.id,
                    "validation_status": report.validation_status,
                    "approval_required": report.human_approval_required,
                },
            }
        )

    if report_ids:
        approvals = session.scalars(select(Approval).where(Approval.project_id == project_id, Approval.report_id.in_(report_ids))).all()
        for approval in approvals:
            events.append(
                {
                    "timestamp": (approval.decided_at or approval.created_at).isoformat(),
                    "event_type": f"approval:{approval.status}",
                    "title": f"Approval {approval.status} for report {approval.report_id}",
                    "details": {"reviewer": approval.reviewer, "decision_reason": approval.decision_reason},
                }
            )

    return sorted(events, key=lambda item: item["timestamp"], reverse=True)


@router.patch("/incidents/{incident_id}/status", dependencies=operator_auth)
def update_incident_status(incident_id: int, payload: IncidentStatusUpdate, project_id: str = Depends(get_project_id), session: Session = Depends(get_session)) -> dict:
    incident = session.get(Incident, incident_id)
    if not incident or incident.project_id != project_id:
        raise HTTPException(status_code=404, detail="incident not found")
    incident.status = payload.status
    incident.updated_at = utc_now()
    audit(
        session,
        f"incident_{payload.status}",
        payload.actor,
        "incident",
        incident.id,
        {"reason": payload.reason},
        project_id,
    )
    session.commit()
    return {"incident_id": incident.id, "status": incident.status}


@router.post("/incidents/{incident_id}/reports", dependencies=operator_auth)
def create_report(
    incident_id: int,
    payload: ReportRequest | None = None,
    project_id: str = Depends(get_project_id),
    session: Session = Depends(get_session),
) -> dict:
    try:
        report = run_report_workflow(session, incident_id, use_external_intel=payload.use_external_intel if payload else False, project_id=project_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.errors()) from exc
    return {"report_id": report.id, "human_approval_required": report.human_approval_required}


@router.get("/reports", dependencies=operator_auth)
def list_reports(project_id: str = Depends(get_project_id), session: Session = Depends(get_session)) -> list[dict]:
    rows = session.scalars(select(OperationalReport).where(OperationalReport.project_id == project_id).order_by(desc(OperationalReport.created_at))).all()
    return [_row_dict(row) for row in rows]


@router.get("/reports/{report_id}", dependencies=operator_auth)
def get_report(report_id: int, project_id: str = Depends(get_project_id), session: Session = Depends(get_session)) -> dict:
    report = session.get(OperationalReport, report_id)
    if not report or report.project_id != project_id:
        raise HTTPException(status_code=404, detail="report not found")
    return _row_dict(report)


@router.get("/reports/{report_id}/evidence", dependencies=operator_auth)
def list_report_evidence(report_id: int, project_id: str = Depends(get_project_id), session: Session = Depends(get_session)) -> list[dict]:
    report = session.get(OperationalReport, report_id)
    if not report or report.project_id != project_id:
        raise HTTPException(status_code=404, detail="report not found")
    if not report.evidence_ids:
        return []
    rows = session.scalars(
        select(EvidenceLog).where(EvidenceLog.project_id == project_id, EvidenceLog.id.in_(report.evidence_ids)).order_by(desc(EvidenceLog.created_at))
    ).all()
    return [_row_dict(row) for row in rows]


@router.get("/reports/{report_id}/approvals", dependencies=operator_auth)
def list_report_approvals(report_id: int, project_id: str = Depends(get_project_id), session: Session = Depends(get_session)) -> list[dict]:
    report = session.get(OperationalReport, report_id)
    if not report or report.project_id != project_id:
        raise HTTPException(status_code=404, detail="report not found")
    rows = session.scalars(select(Approval).where(Approval.project_id == project_id, Approval.report_id == report_id).order_by(desc(Approval.created_at))).all()
    return [_row_dict(row) for row in rows]


@router.get("/approvals", dependencies=operator_auth)
def list_approvals(project_id: str = Depends(get_project_id), session: Session = Depends(get_session)) -> list[dict]:
    rows = session.scalars(select(Approval).where(Approval.project_id == project_id).order_by(desc(Approval.created_at))).all()
    return [_row_dict(row) for row in rows]


@router.post("/approvals/{approval_id}/decision", dependencies=operator_auth)
def decide_approval(approval_id: int, payload: ApprovalDecisionIn, project_id: str = Depends(get_project_id), session: Session = Depends(get_session)) -> dict:
    approval = session.get(Approval, approval_id)
    if not approval or approval.project_id != project_id:
        raise HTTPException(status_code=404, detail="approval not found")
    if approval.status != "pending":
        raise HTTPException(status_code=409, detail="approval already decided")
    report = session.get(OperationalReport, approval.report_id)
    approval.status = payload.status
    approval.reviewer = payload.reviewer
    approval.decision_reason = payload.decision_reason
    approval.decided_at = utc_now()
    if report:
        report.human_approved = payload.status == "approved"
    audit(
        session,
        f"approval_{payload.status}",
        payload.reviewer,
        "approval",
        approval.id,
        {"report_id": approval.report_id, "reason": payload.decision_reason},
        project_id,
    )
    session.commit()
    return {"approval_id": approval.id, "status": approval.status}


@router.get("/audit-logs", dependencies=operator_auth)
def list_audit_logs(project_id: str = Depends(get_project_id), session: Session = Depends(get_session)) -> list[dict]:
    rows = session.scalars(select(AuditLog).where(AuditLog.project_id == project_id).order_by(desc(AuditLog.created_at)).limit(200)).all()
    return [_row_dict(row) for row in rows]


@router.get("/audit-logs/export", dependencies=operator_auth)
def export_audit_logs(project_id: str = Depends(get_project_id), session: Session = Depends(get_session)) -> StreamingResponse:
    rows = session.scalars(select(AuditLog).where(AuditLog.project_id == project_id).order_by(desc(AuditLog.created_at)).limit(1000)).all()
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=["id", "project_id", "event_type", "actor", "entity_type", "entity_id", "details", "created_at"])
    writer.writeheader()
    for row in rows:
        data = _row_dict(row)
        data["details"] = str(data["details"])
        writer.writerow(data)
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="audit-logs.csv"'},
    )


def _row_dict(row) -> dict:
    data = {column.name: getattr(row, column.name) for column in row.__table__.columns}
    for key, value in data.items():
        if hasattr(value, "isoformat"):
            data[key] = value.isoformat()
    return data
