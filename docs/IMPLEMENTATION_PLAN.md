# Implementation Plan

## Phase 1: Governed MVP Foundation

Status: implemented.

- FastAPI API bridge with health, ingestion, incidents, reports, approvals, and audit endpoints.
- React/Vite operator dashboard with Overview, Metrics, Security, Incidents, AI Reports, Approvals, and Audit pages.
- PostgreSQL-compatible SQLAlchemy models for metrics, access logs, incidents, evidence logs, reports, approvals, and audit logs.
- API-key protected metric and access-log ingestion.
- Deterministic incident detection before LLM or agent reasoning.
- Incident dedupe through stable correlation keys.
- Evidence bundles linked to incidents.
- LangGraph workflow nodes for evidence building, crew analysis, schema validation, safety review, human approval gate, and report persistence.
- CrewAI specialist identities with role, goal, and backstory.
- Pydantic report schema validation.
- Human approval required for high-risk recommendations.
- Audit logging for ingestion, incident creation, report generation, and approval decisions.

## Phase 2: Live LLM and Crew Execution

Status: in progress.

- OpenAI structured output is used when `OPENAI_API_KEY` is configured.
- Deterministic fallback remains for local development and CI.
- Run CrewAI tasks for specialist analysis while preserving the LangGraph workflow as the control layer.
- Save model name, prompt version, schema version, raw output, parsed JSON, validation status, and evidence IDs for every report.
- Add tests for malformed model output and fallback behavior.

## Phase 3: Stronger Governance

Status: planned.

- Add reviewer identity support instead of the current demo `operator` reviewer.
- Add approval history views per report and incident.
- Add explicit risk policy rules for remediation classes.
- Add report regeneration controls with version history.
- Add audit export endpoint for V-Model validation evidence.

## Phase 4: Production Hardening

Status: in progress.

- Alembic migration scaffold and initial schema migration are implemented.
- Add authentication for dashboard/API reads.
- Move rate limiting to Redis or gateway infrastructure for multi-instance deployments.
- Add structured logging and request correlation IDs.
- CI runs backend tests, frontend build, and repository hygiene checks.
- Add Railway deployment notes and service-folder configuration.

## Phase 5: Product Expansion

Status: planned.

- Add tenant/project boundaries.
- Add streaming or scheduled data collection integrations.
- Add richer metrics visualizations and incident timelines.
- Add external-intel source provenance in reports.
- Add policy packs for different SaaS operating models.
