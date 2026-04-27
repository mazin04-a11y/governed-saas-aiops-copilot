# Governed SaaS AIOps Copilot

A governed SaaS AIOps copilot MVP with real ingestion, stateful memory, multi-agent orchestration, validated LLM reports, human approval gates, and auditability.

This is not a Datadog or New Relic replacement. It is a production-style product foundation for monitoring SaaS operational and security signals, generating evidence-grounded AI reports, and keeping risky recommendations pending until a human approves or rejects them.

## Product Goal

Build a real SaaS monitoring copilot, not a simulator:

- Ingest operational metrics and access logs through protected APIs.
- Detect incidents with deterministic code before any LLM reasoning runs.
- Build evidence bundles from stored relational data.
- Use LangGraph as the durable workflow control layer.
- Use CrewAI specialist tasks inside selected workflow nodes when configured.
- Generate structured operational reports with OpenAI-compatible output.
- Validate every report with Pydantic before persistence.
- Require human approval for high-risk recommendations.
- Store reports, approvals, evidence links, and audit events in PostgreSQL.

## Architecture

```text
Senses          React/Vite operator dashboard
Nervous System  FastAPI API bridge
Brain           LangGraph workflow + CrewAI specialist reasoning
Memory          PostgreSQL relational state and audit storage
Reliability     Pydantic validation, rate limiting, API-key ingestion
Governance      Human approval gates and audit logs
```

Core principle:

```text
Raw code detects.
LangGraph controls.
CrewAI analyzes.
OpenAI explains.
Pydantic validates.
Human approves.
PostgreSQL audits.
```

## Implemented MVP Surface

- `POST /metrics/ingest`, protected by `X-API-Key`
- `POST /access-logs/ingest`, protected by `X-API-Key`
- optional operator read API protection with `OPERATOR_API_KEYS`
- optional operator username/password login with signed bearer sessions
- deterministic performance and failed-login incident detection
- incident deduplication by correlation key
- evidence logs linked to incidents
- incident timeline across evidence, reports, and approvals
- audited incident resolve/reopen controls
- optional Serper external-intel context inside report generation
- external-intel provenance preserved in report JSON
- OpenAI Responses API structured-output path when `OPENAI_API_KEY` is configured
- LangGraph workflow nodes:
  - `BuildEvidenceBundle`
  - `RunCrewAIAnalysis`
  - `ValidateStructuredOutput`
  - `SafetyReview`
  - `HumanApprovalGate`
  - `SaveOperationalReport`
- CrewAI specialist identities:
  - `ManagerAgent`
  - `PerformanceAnalystAgent`
  - `SecurityAnalystAgent`
  - `ExternalIntelAgent`
  - `RemediationReviewerAgent`
- real CrewAI sequential task execution in `RunCrewAIAnalysis` when `crewai` is installed,
  `CREWAI_EXECUTION_ENABLED=true`, and `OPENAI_API_KEY` is configured
- deterministic CrewAI analysis fallback for local development and CI
- Pydantic operational report schema validation
- report versioning for regenerated incident reports
- high-risk recommendation approval queue
- dashboard approval and rejection actions
- approval history per report
- centralized remediation risk policy for approval decisions
- append-only audit trail for ingestion, incident creation, report saving, and approval decisions
- CSV audit export for validation evidence
- request correlation IDs returned through `X-Request-ID`
- React/Vite pages:
  - Overview
  - Metrics
  - Security
  - Incidents
  - AI Reports
  - Approvals
  - Audit

## Environment

Copy `.env.example` to `.env` and fill values locally:

```bash
DATABASE_URL=postgresql+psycopg://aiops:aiops@postgres:5432/governed_aiops
INGEST_API_KEYS=local-dev-ingest-key
OPERATOR_API_KEYS=
OPERATOR_USERNAME=operator
OPERATOR_PASSWORD=
OPERATOR_SESSION_SECRET=change-me-before-deploy
OPERATOR_SESSION_TTL_SECONDS=3600
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4.1-mini
CREWAI_EXECUTION_ENABLED=true
SERPER_API_KEY=
RATE_LIMIT_REQUESTS=120
RATE_LIMIT_WINDOW_SECONDS=60
VITE_API_BASE_URL=http://localhost:8000
```

Do not commit real API keys.

## Run Locally

```bash
docker compose up --build
```

Then open:

- Dashboard: http://localhost:5173
- API docs: http://localhost:8000/docs
- Health: http://localhost:8000/health

Railway deployment notes are in [`docs/RAILWAY_DEPLOYMENT.md`](docs/RAILWAY_DEPLOYMENT.md).

## Database Migrations

For local MVP bootstrapping, the API can create missing tables on startup. For production-style environments, use Alembic migrations:

```bash
cd backend
alembic upgrade head
```

## API Examples

Ingest a degraded service metric:

```bash
curl -X POST http://localhost:8000/metrics/ingest \
  -H "X-API-Key: local-dev-ingest-key" \
  -H "Content-Type: application/json" \
  -d '{"service_name":"payment-api","cpu_usage":94,"memory_usage":88,"response_time_ms":1250,"error_rate":7.1,"status":"degraded"}'
```

Ingest failed logins:

```bash
curl -X POST http://localhost:8000/access-logs/ingest \
  -H "X-API-Key: local-dev-ingest-key" \
  -H "Content-Type: application/json" \
  -d '{"username":"security_user","action":"login","ip_address":"203.0.113.77","outcome":"failed"}'
```

Generate a governed report for an incident. If `OPENAI_API_KEY` is configured, the backend uses OpenAI structured output and then validates the parsed report with Pydantic. Without an OpenAI key, it uses a deterministic local fallback so the product remains runnable in development and CI:

```bash
curl -X POST http://localhost:8000/incidents/1/reports \
  -H "Content-Type: application/json" \
  -d '{}'
```

If `OPERATOR_PASSWORD` is configured, sign in to the dashboard or request a bearer token directly:

```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"operator","password":"your-password"}'
```

## Validation Evidence

The backend test suite covers:

- no data creates no incidents
- API key required for ingestion
- incident dedupe
- empty evidence prevents hallucinated LLM reports
- invalid LLM schema rejected
- unsafe remediation requires approval or rejection
- high-risk recommendations remain pending

Run:

```bash
cd backend
pytest
```

GitHub Actions also runs backend tests, the frontend production build, and a repository hygiene check that blocks private handover files, `.env`, local databases, dependency folders, and build output from being tracked.

## Governance Notes

- LLMs do not create incidents. Deterministic detection creates incidents from internal data.
- External intelligence is optional context, not a standalone incident source.
- Generated reports must cite stored evidence IDs.
- High-risk recommendations remain pending until reviewed.
- This MVP does not perform autonomous remediation.

## Product Concepts Represented

- Three-Layer Anatomy: senses, nervous system, brain
- Stateful Intelligence and relational memory
- Evidence-grounded generation
- Identity-aware specialist agents with role, goal, and backstory
- Hierarchical Crew pattern
- Resilience stack with guardrails, structural integrity, and metacognition
- Human-in-the-loop approval
- V-Model validation evidence through tests
- Agentic Development Lifecycle
- Auditability and traceability
