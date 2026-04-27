from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.records import AccessLog, EvidenceLog, Incident, SystemMetric
from app.schemas.records import AccessLogIn, MetricIn
from app.services.audit import audit


def ingest_metric(session: Session, payload: MetricIn) -> tuple[SystemMetric, Incident | None]:
    metric = SystemMetric(**payload.model_dump())
    session.add(metric)
    session.flush()
    incident = _detect_performance_incident(session, metric)
    audit(session, "metric_ingested", "api_key", "system_metric", metric.id, {"service_name": metric.service_name})
    session.commit()
    return metric, incident


def ingest_access_log(session: Session, payload: AccessLogIn) -> tuple[AccessLog, Incident | None]:
    access_log = AccessLog(**payload.model_dump())
    session.add(access_log)
    session.flush()
    incident = _detect_security_incident(session, access_log)
    audit(session, "access_log_ingested", "api_key", "access_log", access_log.id, {"username": access_log.username})
    session.commit()
    return access_log, incident


def _detect_performance_incident(session: Session, metric: SystemMetric) -> Incident | None:
    if metric.cpu_usage < 90 and metric.memory_usage < 90 and metric.response_time_ms < 1000 and metric.error_rate < 5:
        return None

    severity = "critical" if metric.error_rate >= 10 or metric.response_time_ms >= 2000 else "high"
    key = f"performance:{metric.service_name}:degraded"
    evidence = EvidenceLog(
        evidence_type="metric_threshold_breach",
        source_table="system_metrics",
        source_id=metric.id,
        summary=f"{metric.service_name} breached performance thresholds.",
        payload={
            "cpu_usage": metric.cpu_usage,
            "memory_usage": metric.memory_usage,
            "response_time_ms": metric.response_time_ms,
            "error_rate": metric.error_rate,
            "status": metric.status,
        },
    )
    return _upsert_incident(
        session,
        key,
        "performance",
        f"{metric.service_name} performance degradation",
        severity,
        "Deterministic threshold detection found operational degradation.",
        evidence,
    )


def _detect_security_incident(session: Session, access_log: AccessLog) -> Incident | None:
    if access_log.outcome.lower() != "failed" or access_log.action.lower() != "login":
        return None

    failed_count = session.scalar(
        select(func.count()).select_from(AccessLog).where(
            AccessLog.username == access_log.username,
            AccessLog.ip_address == access_log.ip_address,
            AccessLog.action == "login",
            AccessLog.outcome == "failed",
        )
    )
    if failed_count is None or failed_count < 3:
        return None

    key = f"security:{access_log.username}:{access_log.ip_address}:failed-logins"
    evidence = EvidenceLog(
        evidence_type="failed_login_cluster",
        source_table="access_logs",
        source_id=access_log.id,
        summary=f"Repeated failed login attempts for {access_log.username} from {access_log.ip_address}.",
        payload={"username": access_log.username, "ip_address": access_log.ip_address, "failed_count": failed_count},
    )
    return _upsert_incident(
        session,
        key,
        "security",
        f"Repeated failed logins for {access_log.username}",
        "high",
        "Deterministic failed-login detection found a suspicious authentication pattern.",
        evidence,
    )


def _upsert_incident(
    session: Session,
    correlation_key: str,
    incident_type: str,
    title: str,
    severity: str,
    description: str,
    evidence: EvidenceLog,
) -> Incident:
    incident = session.scalar(select(Incident).where(Incident.correlation_key == correlation_key, Incident.status == "open"))
    session.add(evidence)
    session.flush()
    if incident:
        incident.occurrence_count += 1
        incident.updated_at = datetime.utcnow()
        incident.evidence_ids = [*incident.evidence_ids, evidence.id]
        evidence.incident_id = incident.id
        audit(session, "incident_deduped", "deterministic_detector", "incident", incident.id, {"evidence_id": evidence.id})
        return incident

    incident = Incident(
        incident_type=incident_type,
        title=title,
        severity=severity,
        correlation_key=correlation_key,
        description=description,
        evidence_ids=[evidence.id],
    )
    session.add(incident)
    session.flush()
    evidence.incident_id = incident.id
    audit(session, "incident_created", "deterministic_detector", "incident", incident.id, {"evidence_id": evidence.id})
    return incident
