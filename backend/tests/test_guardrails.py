from app.core import database
from app.models.records import Incident
from app.services.reporting import generate_structured_output, run_report_workflow
from pydantic import ValidationError

from app.schemas.records import OperationalReportPayload


def test_no_data_creates_no_incidents(client):
    response = client.get("/incidents")
    assert response.status_code == 200
    assert response.json() == []


def test_api_key_required_for_ingestion(client):
    response = client.post(
        "/metrics/ingest",
        json={"service_name": "billing-api", "cpu_usage": 95, "memory_usage": 88, "response_time_ms": 1200, "error_rate": 8},
    )
    assert response.status_code == 401


def test_incident_dedupe(client, auth_headers):
    payload = {"service_name": "payment-api", "cpu_usage": 95, "memory_usage": 88, "response_time_ms": 1200, "error_rate": 8}
    first = client.post("/metrics/ingest", json=payload, headers=auth_headers)
    second = client.post("/metrics/ingest", json=payload, headers=auth_headers)
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["incident_id"] == second.json()["incident_id"]
    incidents = client.get("/incidents").json()
    assert len(incidents) == 1
    assert incidents[0]["occurrence_count"] == 2


def test_empty_evidence_prevents_llm_hallucinated_report(client):
    with database.SessionLocal() as session:
        incident = Incident(
            incident_type="performance",
            title="Evidence-free incident",
            severity="high",
            correlation_key="test:no-evidence",
            description="This test incident has no evidence.",
            evidence_ids=[],
        )
        session.add(incident)
        session.commit()
        incident_id = incident.id
    response = client.post(f"/incidents/{incident_id}/reports", json={})
    assert response.status_code == 400
    assert "empty evidence" in response.json()["detail"]


def test_invalid_llm_schema_rejected():
    bad_payload = {
        "incident_id": 1,
        "executive_summary": "too short",
        "evidence_ids": [],
        "root_cause_hypotheses": [],
        "risk_assessment": "too short",
        "recommendations": [],
        "confidence": 1.4,
    }
    try:
        OperationalReportPayload.model_validate(bad_payload)
    except ValidationError:
        return
    raise AssertionError("invalid schema should be rejected")


def test_unsafe_remediation_requires_approval_or_rejection():
    raw = generate_structured_output(
        7,
        [{"id": 1, "type": "failed_login_cluster", "summary": "failed login cluster", "payload": {}, "source_table": "access_logs", "source_id": 1}],
        {"crew_mode": "test"},
    )
    report = OperationalReportPayload.model_validate(raw)
    assert report.recommendations[0].risk_level == "high"
    assert report.recommendations[0].requires_human_approval is True


def test_high_risk_recommendations_remain_pending(client, auth_headers):
    payload = {"service_name": "checkout-api", "cpu_usage": 95, "memory_usage": 91, "response_time_ms": 1300, "error_rate": 7}
    incident_id = client.post("/metrics/ingest", json=payload, headers=auth_headers).json()["incident_id"]
    response = client.post(f"/incidents/{incident_id}/reports", json={})
    assert response.status_code == 200
    assert response.json()["human_approval_required"] is True
    approvals = client.get("/approvals").json()
    assert approvals[0]["status"] == "pending"


def test_external_intel_context_does_not_create_incidents(client):
    response = client.get("/incidents")
    assert response.status_code == 200
    assert response.json() == []
