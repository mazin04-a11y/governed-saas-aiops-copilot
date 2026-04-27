from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.models.records import Incident
from app.schemas.records import OperationalReportPayload


def generate_openai_structured_report(
    incident: Incident | None,
    evidence: list[dict[str, Any]],
    crew_analysis: dict[str, Any],
) -> OperationalReportPayload | None:
    settings = get_settings()
    if not settings.openai_api_key:
        return None
    if not evidence:
        raise ValueError("cannot generate report without evidence")

    from openai import OpenAI

    client = OpenAI(api_key=settings.openai_api_key)
    response = client.responses.parse(
        model=settings.openai_model,
        input=[
            {
                "role": "system",
                "content": (
                    "You generate governed SaaS AIOps operational reports. "
                    "Use only the supplied evidence IDs and evidence summaries. "
                    "Do not invent incidents, metrics, access logs, causes, or remediation outcomes. "
                    "High-risk recommendations must require human approval."
                ),
            },
            {
                "role": "user",
                "content": _build_report_prompt(incident, evidence, crew_analysis),
            },
        ],
        text_format=OperationalReportPayload,
    )
    return response.output_parsed


def _build_report_prompt(incident: Incident | None, evidence: list[dict[str, Any]], crew_analysis: dict[str, Any]) -> str:
    incident_summary = {
        "id": incident.id if incident else None,
        "title": incident.title if incident else "Unknown incident",
        "type": incident.incident_type if incident else "unknown",
        "severity": incident.severity if incident else "unknown",
        "description": incident.description if incident else "",
    }
    return (
        "Create one structured operational report from this incident, evidence, and crew analysis.\n"
        f"Incident: {incident_summary}\n"
        f"Evidence: {evidence}\n"
        f"Crew analysis: {crew_analysis}\n"
        "Every evidence_ids value in the report must come from the Evidence list. "
        "If a recommendation could affect production access, authentication controls, deployments, "
        "or customer-facing availability, mark it high risk and require human approval."
    )

