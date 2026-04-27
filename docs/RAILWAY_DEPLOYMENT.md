# Railway Deployment

This repo is structured for three Railway services:

- `backend`: FastAPI API bridge
- `frontend`: Vite dashboard
- `Postgres`: Railway managed PostgreSQL

## Backend Service

Service root:

```text
backend
```

Railway can build the backend from `backend/Dockerfile`. The container respects Railway's dynamic `PORT`.

Required variables:

```bash
DATABASE_URL=<Railway Postgres connection string>
INGEST_API_KEYS=<generated comma-separated ingestion keys>
OPERATOR_API_KEYS=<optional generated comma-separated operator dashboard keys>
OPERATOR_USERNAME=operator
OPERATOR_PASSWORD=<optional dashboard login password>
OPERATOR_SESSION_SECRET=<generated session signing secret>
OPERATOR_SESSION_TTL_SECONDS=3600
OPENAI_API_KEY=<OpenAI key, optional for deterministic fallback>
OPENAI_MODEL=gpt-4.1-mini
CREWAI_EXECUTION_ENABLED=true
SERPER_API_KEY=<optional>
RATE_LIMIT_REQUESTS=120
RATE_LIMIT_WINDOW_SECONDS=60
```

The backend container runs Alembic migrations during startup before serving API traffic:

```bash
alembic upgrade head
```

The app still creates missing tables on startup for MVP convenience, but Alembic is the production-style path and is included in the backend image.

## Frontend Service

Service root:

```text
frontend
```

Railway can build the frontend from `frontend/Dockerfile`. The container uses `vite preview` and respects Railway's dynamic `PORT`.

Required variable:

```bash
VITE_API_BASE_URL=https://<backend-service>.up.railway.app
```

## Post-Deploy Smoke Checks

Backend:

```bash
curl https://<backend-service>.up.railway.app/health
```

Protected ingestion should reject missing keys:

```bash
curl -i -X POST https://<backend-service>.up.railway.app/metrics/ingest \
  -H "Content-Type: application/json" \
  -d '{"service_name":"payment-api","cpu_usage":94,"memory_usage":88,"response_time_ms":1250,"error_rate":7.1,"status":"degraded"}'
```

Protected ingestion should accept valid keys:

```bash
curl -X POST https://<backend-service>.up.railway.app/metrics/ingest \
  -H "X-API-Key: <ingest-key>" \
  -H "Content-Type: application/json" \
  -d '{"service_name":"payment-api","cpu_usage":94,"memory_usage":88,"response_time_ms":1250,"error_rate":7.1,"status":"degraded"}'
```

Project-scoped ingestion should isolate records:

```bash
curl -X POST https://<backend-service>.up.railway.app/metrics/ingest \
  -H "X-API-Key: <ingest-key>" \
  -H "X-Project-ID: prod" \
  -H "Content-Type: application/json" \
  -d '{"service_name":"payment-api","cpu_usage":94,"memory_usage":88,"response_time_ms":1250,"error_rate":7.1,"status":"degraded"}'
```

Dashboard:

```text
https://<frontend-service>.up.railway.app
```

## Honest Product Boundary

This deployment is a governed SaaS AIOps copilot MVP. It supports real ingestion, deterministic incident detection, evidence-grounded report generation, approval gates, and audit logs. It is not autonomous remediation and not a Datadog/New Relic replacement.
