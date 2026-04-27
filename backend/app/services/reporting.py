from __future__ import annotations

import os
from typing import Any, TypedDict

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.records import Approval, EvidenceLog, Incident, OperationalReport
from app.schemas.records import OperationalReportPayload, OperationalRecommendation
from app.services.audit import audit
from app.services.external_intel import fetch_external_intel_context
from app.services.openai_reports import generate_openai_structured_report
from app.services.risk_policy import report_requires_approval


class WorkflowState(TypedDict, total=False):
    incident_id: int
    evidence: list[dict[str, Any]]
    crew_analysis: dict[str, Any]
    external_context: dict[str, Any]
    raw_output: dict[str, Any]
    parsed_report: OperationalReportPayload
    validation_status: str
    approval_required: bool
    report_id: int


def build_evidence_bundle(session: Session, incident_id: int) -> list[dict[str, Any]]:
    incident = session.get(Incident, incident_id)
    if not incident:
        raise ValueError("incident not found")
    evidence_rows = session.scalars(select(EvidenceLog).where(EvidenceLog.id.in_(incident.evidence_ids))).all()
    return [
        {
            "id": row.id,
            "type": row.evidence_type,
            "summary": row.summary,
            "payload": row.payload,
            "source_table": row.source_table,
            "source_id": row.source_id,
        }
        for row in evidence_rows
    ]


def run_report_workflow(session: Session, incident_id: int, use_external_intel: bool = False) -> OperationalReport:
    settings = get_settings()

    def build_node(state: WorkflowState) -> WorkflowState:
        evidence = build_evidence_bundle(session, state["incident_id"])
        if not evidence:
            raise ValueError("empty evidence bundle blocks LLM report generation")
        return {**state, "evidence": evidence}

    def crew_node(state: WorkflowState) -> WorkflowState:
        incident = session.get(Incident, state["incident_id"])
        external_context = fetch_external_intel_context(incident, use_external_intel)
        return {
            **state,
            "external_context": external_context,
            "crew_analysis": run_crew_analysis(incident, state["evidence"], external_context),
        }

    def validate_node(state: WorkflowState) -> WorkflowState:
        incident = session.get(Incident, state["incident_id"])
        parsed_from_openai = generate_openai_structured_report(incident, state["evidence"], state["crew_analysis"])
        if parsed_from_openai:
            parsed = parsed_from_openai
            raw_output = parsed.model_dump()
        else:
            raw_output = generate_structured_output(
                state["incident_id"],
                state["evidence"],
                state["crew_analysis"],
                state.get("external_context"),
            )
            parsed = OperationalReportPayload.model_validate(raw_output)
        return {**state, "raw_output": raw_output, "parsed_report": parsed, "validation_status": "valid"}

    def safety_node(state: WorkflowState) -> WorkflowState:
        parsed = state["parsed_report"]
        approval_required = report_requires_approval(parsed.recommendations)
        return {**state, "approval_required": approval_required}

    def approval_node(state: WorkflowState) -> WorkflowState:
        return state

    def save_node(state: WorkflowState) -> WorkflowState:
        parsed = state["parsed_report"]
        approval_required = state["approval_required"]
        next_version = (
            session.scalar(
                select(func.coalesce(func.max(OperationalReport.report_version), 0) + 1).where(
                    OperationalReport.incident_id == state["incident_id"]
                )
            )
            or 1
        )
        report = OperationalReport(
            incident_id=state["incident_id"],
            report_version=next_version,
            model_name=settings.openai_model,
            prompt_version=settings.prompt_version,
            schema_version=settings.schema_version,
            raw_llm_output=state["raw_output"],
            parsed_json={**parsed.model_dump(), "external_context": state.get("external_context", {"status": "skipped", "items": []})},
            validation_status=state["validation_status"],
            human_approval_required=approval_required,
            human_approved=False if approval_required else True,
            evidence_ids=parsed.evidence_ids,
        )
        session.add(report)
        session.flush()
        if approval_required:
            session.add(Approval(report_id=report.id, status="pending"))
        audit(
            session,
            "operational_report_saved",
            "langgraph_workflow",
            "operational_report",
            report.id,
            {"incident_id": report.incident_id, "approval_required": approval_required},
        )
        session.commit()
        return {**state, "report_id": report.id}

    workflow = _compile_workflow(build_node, crew_node, validate_node, safety_node, approval_node, save_node)
    try:
        final_state = workflow.invoke({"incident_id": incident_id})
    except ValidationError:
        audit(session, "operational_report_rejected", "pydantic_validator", "incident", incident_id, {"reason": "invalid_schema"})
        session.commit()
        raise
    report = session.get(OperationalReport, final_state["report_id"])
    if report is None:
        raise RuntimeError("workflow completed without saved report")
    return report


def _compile_workflow(build_node, crew_node, validate_node, safety_node, approval_node, save_node):
    try:
        from langgraph.graph import END, StateGraph

        graph = StateGraph(WorkflowState)
        graph.add_node("BuildEvidenceBundle", build_node)
        graph.add_node("RunCrewAIAnalysis", crew_node)
        graph.add_node("ValidateStructuredOutput", validate_node)
        graph.add_node("SafetyReview", safety_node)
        graph.add_node("HumanApprovalGate", approval_node)
        graph.add_node("SaveOperationalReport", save_node)
        graph.set_entry_point("BuildEvidenceBundle")
        graph.add_edge("BuildEvidenceBundle", "RunCrewAIAnalysis")
        graph.add_edge("RunCrewAIAnalysis", "ValidateStructuredOutput")
        graph.add_edge("ValidateStructuredOutput", "SafetyReview")
        graph.add_edge("SafetyReview", "HumanApprovalGate")
        graph.add_edge("HumanApprovalGate", "SaveOperationalReport")
        graph.add_edge("SaveOperationalReport", END)
        return graph.compile()
    except Exception:
        class SequentialWorkflow:
            def invoke(self, state: WorkflowState) -> WorkflowState:
                for node in (build_node, crew_node, validate_node, safety_node, approval_node, save_node):
                    state = node(state)
                return state

        return SequentialWorkflow()


def run_crew_analysis(incident: Incident | None, evidence: list[dict[str, Any]], external_context: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = get_settings()
    agents = _crew_agent_specs()
    if not settings.crewai_execution_enabled:
        return _deterministic_crew_analysis(incident, evidence, external_context, agents, "crewai_disabled")
    if not settings.openai_api_key:
        return _deterministic_crew_analysis(incident, evidence, external_context, agents, "openai_api_key_not_configured")
    try:
        return _run_crewai_tasks(incident, evidence, external_context, agents, settings.openai_api_key, settings.openai_model)
    except Exception as exc:
        return _deterministic_crew_analysis(incident, evidence, external_context, agents, f"crewai_unavailable:{exc.__class__.__name__}")


def _crew_agent_specs() -> list[dict[str, str]]:
    return [
        {
            "name": "ManagerAgent",
            "role": "Hierarchical crew manager",
            "goal": "Coordinate specialist reasoning and preserve evidence discipline.",
            "backstory": "A calm operations lead who refuses to let unsupported claims into reports.",
        },
        {
            "name": "PerformanceAnalystAgent",
            "role": "Performance analyst",
            "goal": "Explain metric threshold breaches using only internal evidence.",
            "backstory": "A reliability engineer focused on latency, saturation, and user impact.",
        },
        {
            "name": "SecurityAnalystAgent",
            "role": "Security analyst",
            "goal": "Assess identity-aware access patterns and authentication risk.",
            "backstory": "A security reviewer trained to separate suspicion from proof.",
        },
        {
            "name": "ExternalIntelAgent",
            "role": "External context analyst",
            "goal": "Use optional public intelligence only as context, never as incident source.",
            "backstory": "A threat-intel specialist with a strict provenance habit.",
        },
        {
            "name": "RemediationReviewerAgent",
            "role": "Remediation reviewer",
            "goal": "Flag risky actions for human approval.",
            "backstory": "A change-management reviewer who keeps production blast radius visible.",
        },
    ]


def _deterministic_crew_analysis(
    incident: Incident | None,
    evidence: list[dict[str, Any]],
    external_context: dict[str, Any] | None,
    agents: list[dict[str, str]],
    fallback_reason: str,
) -> dict[str, Any]:
    return {
        "crew_mode": "deterministic-fallback",
        "fallback_reason": fallback_reason,
        "agents": agents,
        "incident_title": incident.title if incident else "Unknown incident",
        "evidence_count": len(evidence),
        "external_context": external_context or {"status": "skipped", "items": []},
    }


def _run_crewai_tasks(
    incident: Incident | None,
    evidence: list[dict[str, Any]],
    external_context: dict[str, Any] | None,
    agent_specs: list[dict[str, str]],
    openai_api_key: str,
    openai_model: str,
) -> dict[str, Any]:
    from crewai import Agent, Crew, Process, Task

    previous_api_key = os.environ.get("OPENAI_API_KEY")
    previous_model = os.environ.get("OPENAI_MODEL_NAME")
    os.environ["OPENAI_API_KEY"] = openai_api_key
    os.environ.setdefault("OPENAI_MODEL_NAME", openai_model)
    try:
        agent_by_name = {
            spec["name"]: Agent(
                role=spec["role"],
                goal=spec["goal"],
                backstory=spec["backstory"],
                verbose=False,
                allow_delegation=spec["name"] == "ManagerAgent",
            )
            for spec in agent_specs
        }
        incident_summary = {
            "id": incident.id if incident else None,
            "title": incident.title if incident else "Unknown incident",
            "type": incident.incident_type if incident else "unknown",
            "severity": incident.severity if incident else "unknown",
            "description": incident.description if incident else "",
        }
        evidence_summary = [
            {"id": item["id"], "type": item["type"], "summary": item["summary"], "payload": item.get("payload", {})}
            for item in evidence
        ]
        external_summary = external_context or {"status": "skipped", "items": []}
        shared_context = (
            f"Incident: {incident_summary}\n"
            f"Stored evidence: {evidence_summary}\n"
            f"External context: {external_summary}\n"
            "Rules: use only stored evidence IDs, do not create incidents, and treat external context as provenance only."
        )
        task_specs = [
            (
                "performance_analysis",
                "Identify performance signals and user-impact hypotheses supported by stored metric evidence.",
                "A concise evidence-grounded performance assessment with cited evidence IDs.",
                "PerformanceAnalystAgent",
            ),
            (
                "security_analysis",
                "Identify authentication or access-pattern risk supported by stored access-log evidence.",
                "A concise evidence-grounded security assessment with cited evidence IDs.",
                "SecurityAnalystAgent",
            ),
            (
                "external_context_review",
                "Summarize any optional external context and clearly state that it is not an incident source.",
                "A provenance-aware external context note.",
                "ExternalIntelAgent",
            ),
            (
                "remediation_review",
                "Review likely remediation themes and flag production-impacting actions for human approval.",
                "A remediation risk review with approval-sensitive actions called out.",
                "RemediationReviewerAgent",
            ),
            (
                "manager_synthesis",
                "Synthesize the specialist findings into a governed report brief without unsupported claims.",
                "A final governed synthesis that preserves evidence discipline and approval boundaries.",
                "ManagerAgent",
            ),
        ]
        tasks = [
            Task(
                description=f"{description}\n\n{shared_context}",
                expected_output=expected_output,
                agent=agent_by_name[agent_name],
            )
            for _, description, expected_output, agent_name in task_specs
        ]
        crew = Crew(
            agents=list(agent_by_name.values()),
            tasks=tasks,
            process=Process.sequential,
            verbose=False,
        )
        output = crew.kickoff()
    finally:
        if previous_api_key is None:
            os.environ.pop("OPENAI_API_KEY", None)
        else:
            os.environ["OPENAI_API_KEY"] = previous_api_key
        if previous_model is None:
            os.environ.pop("OPENAI_MODEL_NAME", None)
        else:
            os.environ["OPENAI_MODEL_NAME"] = previous_model

    task_outputs = _serialize_crewai_task_outputs(getattr(output, "tasks_output", None))
    return {
        "crew_mode": "crewai-executed",
        "agents": agent_specs,
        "incident_title": incident.title if incident else "Unknown incident",
        "evidence_count": len(evidence),
        "external_context": external_context or {"status": "skipped", "items": []},
        "task_names": [name for name, *_ in task_specs],
        "task_outputs": task_outputs,
        "final_output": getattr(output, "raw", str(output)),
    }


def _serialize_crewai_task_outputs(task_outputs: Any) -> list[str]:
    if not task_outputs:
        return []
    return [getattr(task_output, "raw", str(task_output)) for task_output in task_outputs]


def generate_structured_output(
    incident_id: int,
    evidence: list[dict[str, Any]],
    crew_analysis: dict[str, Any],
    external_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not evidence:
        raise ValueError("cannot generate report without evidence")
    evidence_ids = [item["id"] for item in evidence]
    first = evidence[0]
    high_risk = first["type"] in {"failed_login_cluster", "metric_threshold_breach"}
    recommendation = OperationalRecommendation(
        title="Review and approve governed remediation",
        rationale="The recommendation is tied to stored evidence and should be reviewed before production action.",
        risk_level="high" if high_risk else "medium",
        requires_human_approval=high_risk,
    )
    return {
        "incident_id": incident_id,
        "executive_summary": f"Incident {incident_id} is supported by {len(evidence)} stored evidence item(s).",
        "evidence_ids": evidence_ids,
        "root_cause_hypotheses": [f"Evidence {first['id']} indicates {first['summary']}"],
        "risk_assessment": "Risk is based on deterministic detection and specialist review; unsupported claims are excluded.",
        "recommendations": [recommendation.model_dump()],
        "confidence": 0.74,
        "crew_analysis": crew_analysis,
        "external_context": external_context or {"status": "skipped", "items": []},
    }
