import sys
from types import SimpleNamespace

from app.core import database
from app.core.config import get_settings
from app.models.records import Incident
from app.schemas.records import OperationalReportPayload
from app.services.reporting import generate_structured_output, run_crew_analysis, run_report_workflow
from app.services.risk_policy import recommendation_requires_approval
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


def test_operator_login_session_can_protect_dashboard_endpoints(client, monkeypatch):
    monkeypatch.setenv("OPERATOR_USERNAME", "ops")
    monkeypatch.setenv("OPERATOR_PASSWORD", "secret-password")
    monkeypatch.setenv("OPERATOR_SESSION_SECRET", "test-session-secret")
    get_settings.cache_clear()
    try:
        assert client.get("/incidents").status_code == 401
        login = client.post("/auth/login", json={"username": "ops", "password": "secret-password"})
        assert login.status_code == 200
        token = login.json()["access_token"]
        response = client.get("/incidents", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        assert client.get("/incidents", headers={"Authorization": "Bearer bad.token"}).status_code == 401
    finally:
        monkeypatch.delenv("OPERATOR_USERNAME", raising=False)
        monkeypatch.delenv("OPERATOR_PASSWORD", raising=False)
        monkeypatch.delenv("OPERATOR_SESSION_SECRET", raising=False)
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


def test_project_boundaries_scope_detection_and_reads(client, auth_headers):
    payload = {"service_name": "tenant-api", "cpu_usage": 95, "memory_usage": 88, "response_time_ms": 1200, "error_rate": 8}
    alpha_headers = {**auth_headers, "X-Project-ID": "alpha"}
    beta_headers = {**auth_headers, "X-Project-ID": "beta"}

    alpha_incident = client.post("/metrics/ingest", json=payload, headers=alpha_headers).json()["incident_id"]
    beta_incident = client.post("/metrics/ingest", json=payload, headers=beta_headers).json()["incident_id"]

    assert alpha_incident != beta_incident
    alpha_incidents = client.get("/incidents", headers={"X-Project-ID": "alpha"}).json()
    beta_incidents = client.get("/incidents", headers={"X-Project-ID": "beta"}).json()
    assert [incident["project_id"] for incident in alpha_incidents] == ["alpha"]
    assert [incident["project_id"] for incident in beta_incidents] == ["beta"]
    assert client.get(f"/incidents/{alpha_incident}", headers={"X-Project-ID": "beta"}).status_code == 404

    projects = {project["id"] for project in client.get("/projects").json()}
    assert {"alpha", "beta"}.issubset(projects)


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


def test_crewai_analysis_uses_deterministic_fallback_without_openai_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    get_settings.cache_clear()
    try:
        incident = Incident(
            incident_type="performance",
            title="Fallback incident",
            severity="high",
            correlation_key="test:fallback",
            description="A fallback test incident.",
            evidence_ids=[1],
        )
        analysis = run_crew_analysis(
            incident,
            [{"id": 1, "type": "metric_threshold_breach", "summary": "latency threshold breached", "payload": {}}],
        )
    finally:
        get_settings.cache_clear()
    assert analysis["crew_mode"] == "deterministic-fallback"
    assert analysis["fallback_reason"] == "openai_api_key_not_configured"
    assert {agent["name"] for agent in analysis["agents"]} == {
        "ManagerAgent",
        "PerformanceAnalystAgent",
        "SecurityAnalystAgent",
        "ExternalIntelAgent",
        "RemediationReviewerAgent",
    }


def test_crewai_analysis_runs_real_tasks_when_configured(monkeypatch):
    created = {"agents": [], "tasks": [], "crew": None}

    class FakeAgent:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            created["agents"].append(kwargs)

    class FakeTask:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            created["tasks"].append(kwargs)

    class FakeCrew:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            created["crew"] = kwargs

        def kickoff(self):
            return SimpleNamespace(
                raw="manager synthesis",
                tasks_output=[SimpleNamespace(raw=f"task-output-{index}") for index in range(len(self.kwargs["tasks"]))],
            )

    fake_crewai = SimpleNamespace(
        Agent=FakeAgent,
        Task=FakeTask,
        Crew=FakeCrew,
        Process=SimpleNamespace(sequential="sequential"),
    )
    monkeypatch.setitem(sys.modules, "crewai", fake_crewai)
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.delenv("OPENAI_MODEL_NAME", raising=False)
    get_settings.cache_clear()
    try:
        incident = Incident(
            incident_type="security",
            title="Configured incident",
            severity="high",
            correlation_key="test:configured",
            description="A configured CrewAI test incident.",
            evidence_ids=[3],
        )
        analysis = run_crew_analysis(
            incident,
            [{"id": 3, "type": "failed_login_cluster", "summary": "failed login cluster", "payload": {"count": 5}}],
            {"status": "ok", "items": [{"title": "Vendor status"}]},
        )
    finally:
        get_settings.cache_clear()

    assert analysis["crew_mode"] == "crewai-executed"
    assert analysis["task_names"] == [
        "performance_analysis",
        "security_analysis",
        "external_context_review",
        "remediation_review",
        "manager_synthesis",
    ]
    assert analysis["task_outputs"][-1] == "task-output-4"
    assert len(created["agents"]) == 5
    assert len(created["tasks"]) == 5
    assert created["crew"]["process"] == "sequential"


def test_policy_flags_production_recommendations_for_approval():
    recommendation = OperationalReportPayload.model_validate(
        {
            "incident_id": 1,
            "executive_summary": "Evidence supports a production-impacting mitigation.",
            "evidence_ids": [1],
            "root_cause_hypotheses": ["Metric evidence indicates service degradation."],
            "risk_assessment": "The action may affect production availability.",
            "recommendations": [
                {
                    "title": "Restart production service",
                    "rationale": "Restart the production service after operator review.",
                    "risk_level": "medium",
                    "requires_human_approval": False,
                }
            ],
            "confidence": 0.7,
        }
    ).recommendations[0]
    assert recommendation_requires_approval(recommendation) is True


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


def test_operator_can_retrieve_report_approval_history(client, auth_headers):
    payload = {"service_name": "approval-history-api", "cpu_usage": 95, "memory_usage": 91, "response_time_ms": 1300, "error_rate": 7}
    incident_id = client.post("/metrics/ingest", json=payload, headers=auth_headers).json()["incident_id"]
    report_id = client.post(f"/incidents/{incident_id}/reports", json={}).json()["report_id"]
    response = client.get(f"/reports/{report_id}/approvals")
    assert response.status_code == 200
    assert response.json()[0]["report_id"] == report_id


def test_regenerated_reports_increment_version(client, auth_headers):
    payload = {"service_name": "versioned-api", "cpu_usage": 95, "memory_usage": 91, "response_time_ms": 1300, "error_rate": 7}
    incident_id = client.post("/metrics/ingest", json=payload, headers=auth_headers).json()["incident_id"]
    first = client.post(f"/incidents/{incident_id}/reports", json={}).json()["report_id"]
    second = client.post(f"/incidents/{incident_id}/reports", json={}).json()["report_id"]
    reports = {row["id"]: row for row in client.get("/reports").json()}
    assert reports[first]["report_version"] == 1
    assert reports[second]["report_version"] == 2


def test_incident_timeline_combines_evidence_and_reports(client, auth_headers):
    payload = {"service_name": "timeline-api", "cpu_usage": 95, "memory_usage": 91, "response_time_ms": 1300, "error_rate": 7}
    incident_id = client.post("/metrics/ingest", json=payload, headers=auth_headers).json()["incident_id"]
    client.post(f"/incidents/{incident_id}/reports", json={})
    response = client.get(f"/incidents/{incident_id}/timeline")
    assert response.status_code == 200
    event_types = {item["event_type"] for item in response.json()}
    assert "incident_created" in event_types
    assert "evidence:metric_threshold_breach" in event_types
    assert "report_saved" in event_types


def test_operator_can_resolve_incident_with_audit(client, auth_headers):
    payload = {"service_name": "resolve-api", "cpu_usage": 95, "memory_usage": 91, "response_time_ms": 1300, "error_rate": 7}
    incident_id = client.post("/metrics/ingest", json=payload, headers=auth_headers).json()["incident_id"]
    response = client.patch(
        f"/incidents/{incident_id}/status",
        json={"status": "resolved", "actor": "operator", "reason": "Mitigation validated."},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "resolved"
    audit_rows = client.get("/audit-logs").json()
    assert any(row["event_type"] == "incident_resolved" and row["entity_id"] == incident_id for row in audit_rows)


def test_external_intel_context_does_not_create_incidents(client):
    response = client.get("/incidents")
    assert response.status_code == 200
    assert response.json() == []


def test_external_intel_context_is_preserved_as_report_provenance(client, auth_headers):
    payload = {"service_name": "intel-api", "cpu_usage": 95, "memory_usage": 91, "response_time_ms": 1300, "error_rate": 7}
    incident_id = client.post("/metrics/ingest", json=payload, headers=auth_headers).json()["incident_id"]
    client.post(f"/incidents/{incident_id}/reports", json={"use_external_intel": True})
    report = client.get("/reports").json()[0]
    assert report["parsed_json"]["external_context"]["status"] in {"not_configured", "ok", "failed"}


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
