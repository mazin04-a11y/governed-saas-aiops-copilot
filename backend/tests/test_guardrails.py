from app.core import database
from app.core.config import get_settings
from app.models.records import Incident
from app.schemas.records import OperationalReportPayload
from app.services.reporting import generate_structured_output, run_report_workflow
from pydantic import ValidationError


def test_no_data_creates_no_incidents(client):
    response = client.get("/incidents")
    assert response.status_code == 200
    assert response.json() == []


def test_request_id_header_is_returned(client):
    response = client.get("/health", headers={"X-Request-ID": "test-correlation-id"})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "test-correlation-id"


def test_operator_api_key_can_protect_read_endpoints(client, monkeypatch):
    monkeypatch.setenv("OPERATOR_API_KEYS", "operator-key")
    get_settings.cache_clear()
    try:
        assert client.get("/incidents").status_code == 401
        assert client.get("/incidents", headers={"X-API-Key": "operator-key"}).status_code == 200
    finally:
        monkeypatch.delenv("OPERATOR_API_KEYS", raising=False)
        get_settings.cache_clear()


def test_audit_logs_export_csv(client, auth_headers):
    client.post(
        "/metrics/ingest",
        json={"service_name": "audit-api", "cpu_usage": 91, "memory_usage": 82, "response_time_ms": 1050, "error_rate": 5.5},
        headers=auth_headers,
    )
    response = client.get("/audit-logs/export")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "event_type" in response.text
    assert "metric_ingested" in response.text


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


def test_operator_can_retrieve_incident_evidence(client, auth_headers):
    payload = {"service_name": "evidence-api", "cpu_usage": 95, "memory_usage": 88, "response_time_ms": 1200, "error_rate": 8}
    incident_id = client.post("/metrics/ingest", json=payload, headers=auth_headers).json()["incident_id"]
    response = client.get(f"/incidents/{incident_id}/evidence")
    assert response.status_code == 200
    evidence = response.json()
    assert len(evidence) == 1
    assert evidence[0]["evidence_type"] == "metric_threshold_breach"
    assert evidence[0]["payload"]["response_time_ms"] == 1200


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


def test_operator_can_retrieve_report_evidence(client, auth_headers):
    payload = {"service_name": "report-evidence-api", "cpu_usage": 95, "memory_usage": 91, "response_time_ms": 1300, "error_rate": 7}
    incident_id = client.post("/metrics/ingest", json=payload, headers=auth_headers).json()["incident_id"]
    report_id = client.post(f"/incidents/{incident_id}/reports", json={}).json()["report_id"]
    response = client.get(f"/reports/{report_id}/evidence")
    assert response.status_code == 200
    assert response.json()[0]["incident_id"] == incident_id


def test_regenerated_reports_increment_version(client, auth_headers):
    payload = {"service_name": "versioned-api", "cpu_usage": 95, "memory_usage": 91, "response_time_ms": 1300, "error_rate": 7}
    incident_id = client.post("/metrics/ingest", json=payload, headers=auth_headers).json()["incident_id"]
    first = client.post(f"/incidents/{incident_id}/reports", json={}).json()["report_id"]
    second = client.post(f"/incidents/{incident_id}/reports", json={}).json()["report_id"]
    reports = {row["id"]: row for row in client.get("/reports").json()}
    assert reports[first]["report_version"] == 1
    assert reports[second]["report_version"] == 2


def test_external_intel_context_does_not_create_incidents(client):
    response = client.get("/incidents")
    assert response.status_code == 200
    assert response.json() == []


def test_openai_structured_report_path_saves_validated_payload(client, auth_headers, monkeypatch):
    payload = {"service_name": "reports-api", "cpu_usage": 93, "memory_usage": 86, "response_time_ms": 1180, "error_rate": 6}
    incident_id = client.post("/metrics/ingest", json=payload, headers=auth_headers).json()["incident_id"]

    def fake_openai_report(incident, evidence, crew_analysis):
        return OperationalReportPayload.model_validate(
            {
                "incident_id": incident.id,
                "executive_summary": "OpenAI structured output produced an evidence-grounded report.",
                "evidence_ids": [item["id"] for item in evidence],
                "root_cause_hypotheses": ["Stored metric evidence indicates service degradation."],
                "risk_assessment": "Recommendation affects production behavior and must be reviewed.",
                "recommendations": [
                    {
                        "title": "Review production mitigation",
                        "rationale": "The proposed mitigation changes production operations.",
                        "risk_level": "high",
                        "requires_human_approval": True,
                    }
                ],
                "confidence": 0.82,
            }
        )

    monkeypatch.setattr("app.services.reporting.generate_openai_structured_report", fake_openai_report)
    response = client.post(f"/incidents/{incident_id}/reports", json={})
    assert response.status_code == 200
    assert response.json()["human_approval_required"] is True

    report = client.get("/reports").json()[0]
    assert report["validation_status"] == "valid"
    assert report["parsed_json"]["confidence"] == 0.82
