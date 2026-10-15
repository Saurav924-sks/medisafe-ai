# MediSafe AI

MediSafe AI is a **production-oriented clinical decision support prototype**. It must not be used to direct patient care. A clinician remains responsible for reviewing source data, analysis limitations, and any alert.

## Components and status

| Component | Status |
|---|---|
| React clinician workflow | Implemented; patient history, observations, encounters, and prescriptions use protected backend reads |
| FastAPI API, organization scoping, API-key plus clinician-ID authentication | Partial; no identity provider or per-user credential exchange |
| PostgreSQL schema and Alembic migrations | Implemented; clean and development DB migration checks must be rerun per release |
| SQLite synthetic test workflows | Implemented |
| Structured medication normalization and analysis persistence | Partial; catalog coverage and provenance are limited |
| Versioned knowledge import/review/activation/rollback | Implemented; version 1 is prototype data pending clinical review |
| Deterministic safety checks and alert review/audit | Partial; limited rules and domains; no clinical-use evidence is claimed |
| FHIR mappings and validation adapter | Partial; see [FHIR_INTEGRATION.md](docs/FHIR_INTEGRATION.md) |
| SMART authorization-code + PKCE primitives | Partial; in-memory token state is not deployment-ready |
| Clinical validation | No clinical validation evidence is available |

Detailed descriptions and limitations: [ARCHITECTURE.md](docs/ARCHITECTURE.md), [SECURITY.md](docs/SECURITY.md), [CLINICAL_SAFETY.md](docs/CLINICAL_SAFETY.md), [DATA_MODEL.md](docs/DATA_MODEL.md), [FHIR_INTEGRATION.md](docs/FHIR_INTEGRATION.md), [docs/PROGRESS.md](docs/PROGRESS.md).

## Architecture

The React/Vite frontend sends JSON requests to the FastAPI service under `/api/v1`. API dependencies validate the configured organization credential, resolve the clinician identity and role, then scope patient and clinical records to that clinician's organization. SQLAlchemy persists normalized records, versioned knowledge, analysis snapshots, alert decisions, feedback, and audit events. Analysis calls deterministic rules against an explicitly selected active knowledge version; FHIR resources pass through a versioned validation and normalization adapter before entering the same analysis path. See [ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Requirements and local setup

Use Python 3.11 or newer, Node.js 20 or newer, and PostgreSQL 15 for the configured development database. SQLite is used by synthetic tests. Install dependencies from the checked-in manifests; do not copy real patient information into fixtures.

From PowerShell at the repository root:

```powershell
Copy-Item .env.example .env
# Edit .env and set organization/database credentials locally.
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r frontend\backend\requirements.txt
Set-Location frontend
npm ci
Set-Location ..
```

`API_KEY` must be set to a strong deployment-managed value. Configure `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT`, and `POSTGRES_DB`. `DATABASE_URL` can override PostgreSQL for isolated local runs, for example `sqlite:///./medisafe-local.db`. Never commit `.env`; `.env.example` contains placeholders only. The backend fails closed for API requests when `API_KEY` is unset.

## Local dev quickstart

For local SQLite development, ensure the repository-root `.env` contains:

```dotenv
DATABASE_URL=sqlite:///./medisafe-local.db
API_KEY=<your-local-development-api-key>
```

The SQLite URL is relative to the backend working directory, so this uses
`frontend/backend/medisafe-local.db`. The backend loads the repository-root
`.env`. Do not print or commit the API key.

The frontend API origin is configured with `VITE_API_BASE_URL`; if unset, it
uses `http://localhost:8000` and appends `/api/v1`. For example, a frontend
`.env.local` can contain `VITE_API_BASE_URL=http://localhost:8000`.
Backend CORS origins are read from the comma-separated `CORS_ORIGINS`
environment variable; its default permits `http://localhost:5173` and
`http://localhost:3000`.

First, apply migrations and create the idempotent synthetic local seed records:

```powershell
Set-Location "C:\CHANDAN\medisafe-ai_ML\frontend\backend"
..\..\.venv\Scripts\Activate.ps1
python .\scripts\seed_dev.py
```

The script prints the admin/prescriber and read-only clinician IDs. Use the
chosen ID in `X-Clinician-ID` and the local `.env` API key in `X-API-Key`.
For the clean local seed database, clinician ID **1** is the synthetic
admin/prescriber (`ADMIN`, `DOCTOR`) and clinician ID **2** is synthetic
read-only (`READ_ONLY`). The IDs and credentials are local development values;
do not use real patient data.
The sign-in screen sends both headers to `GET /api/v1/auth/session` and stores
the credentials in tab-scoped `sessionStorage` after successful validation.

The local seed applies Alembic migrations before creating synthetic users.
Application imports do not apply schema migrations. If you skip the seed, run
`python -m alembic upgrade head` from `frontend\backend` before starting the API.

Terminal 1 — backend on port 8000:

```powershell
Set-Location "C:\CHANDAN\medisafe-ai_ML\frontend\backend"
..\..\.venv\Scripts\Activate.ps1
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Terminal 2 — frontend on port 5173:

```powershell
Set-Location "C:\CHANDAN\medisafe-ai_ML"
npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173
```

Verify with `GET http://localhost:8000/api/health` and open the frontend at
`http://localhost:5173`. Do not expose development ports publicly.

## Start and develop

The repository root `package.json` defines these commands:

```powershell
# Terminal 1, backend from frontend/backend
npm run dev:backend

# Terminal 2, frontend at Vite's development URL
npm run dev:frontend
```

The `dev:backend` script applies Alembic migrations before starting the API. The health endpoint is `GET http://localhost:8000/api/health`. The frontend development server uses `http://localhost:5173`. Docker Compose configuration and Dockerfile paths are present, but a container build/runtime has not been verified; this is not a production deployment path. Do not expose development ports publicly.

## Database and data model

Alembic migration files are in `frontend/backend/migrations/versions`. Persistent entities include organizations, users and roles, patients and legacy clinical lists, medication catalog entries and ingredients, prescriptions and orders, knowledge versions and clinical rules, analyses and alerts, separate alert review action records, feedback, and audit events. Alert actions do not rewrite or delete the original alert. See [DATA_MODEL.md](docs/DATA_MODEL.md). Back up the database and test migrations against both an empty database and a copy of the target database before upgrades.

## Authentication, authorization, and audit

The API accepts `X-API-Key` and `X-Clinician-ID`; role checks and organization scoping are enforced by backend dependencies. The shared API key is a prototype boundary, not production authentication and not a substitute for an identity provider, MFA, individual secrets, rate limiting, or a production session service. The frontend validates sign-in through `GET /api/v1/auth/session` and keeps credentials in tab-scoped `sessionStorage`. Audit events record actor/record identifiers and action metadata; avoid putting names, clinical details, credentials, or tokens in audit detail fields. See [SECURITY.md](docs/SECURITY.md).

## Clinical workflow

The intended workflow is clinician sign-in, patient search or registration, patient profile, structured prescription, normalization review, pre-analysis validation, analysis, and alert review or override. Medication History, Observations, Encounters, and Prescriptions load from organization-scoped backend read APIs; the Audit tab remains explicitly unavailable because there is no patient audit read endpoint. Never interpret no alerts as safety. Missing, stale, unavailable, or unnormalized context must remain explicit. Analysis status and checked versus unchecked domains are shown with each result. See [CLINICAL_SAFETY.md](docs/CLINICAL_SAFETY.md).

## Safety engine and knowledge base

The engine uses deterministic rules and versioned knowledge data; parsing and normalization are not clinical decisions. Knowledge imports follow import, validate, normalize, version, clinical review, activate, and audit steps. Only an authorized clinical reviewer can activate a version, and rollback is recorded. Version 1 is marked “prototype data — not clinically reviewed” until signed off. Feedback supports analytics, queues, and rule-quality monitoring only; it does not change rules. Rule changes require a separately reviewed, versioned, reversible workflow. The implemented rule set is limited; no clinical-use evidence is claimed.

## FHIR and SMART

FHIR integrations live in the backend adapter, not React. Only documented mappings are accepted and all external resources are validated before normalization and analysis. SMART authorization-code and PKCE primitives are present; token lifecycle persistence and production client registration are partial. No FHIR sandbox or real patient data is used in normal workflows. See [FHIR_INTEGRATION.md](docs/FHIR_INTEGRATION.md). No ABDM compliance is claimed.

## Security and privacy

Use synthetic records only outside an appropriately governed clinical environment. Use TLS at a trusted ingress, managed secret storage, least-privilege database accounts, restricted network access, backups, monitoring, and a reviewed identity provider before deployment. Tokens must never be logged or committed. Review [SECURITY.md](docs/SECURITY.md) and [CLINICAL_SAFETY.md](docs/CLINICAL_SAFETY.md) before any clinical evaluation.

## Testing and quality checks

```powershell
Set-Location frontend\backend
..\..\.venv\Scripts\python.exe -m pytest -q
Set-Location ..
npm test
npm run lint
npm run build
# From the repository root, run the isolated real-HTTP workflow
Set-Location ..
Set-Location frontend\backend
..\..\.venv\Scripts\python.exe .\scripts\e2e_smoke.py
```

The backend test suite lives under `frontend/backend/tests`; standalone demos are in `frontend/backend/scripts` and `frontend/scripts`, outside pytest test-file naming. Tests and the HTTP smoke workflow use synthetic data and SQLite; they do not validate clinical performance or production PostgreSQL behavior. The smoke workflow intentionally reports blocked prescription/analysis steps when no clinically reviewed knowledge version is active. Check migration behavior on clean and copied existing databases, `/api/health`, secret scans, and `git diff --check` before releases. Record actual output and any unavailable gate in [docs/PROGRESS.md](docs/PROGRESS.md).

## Deployment and clinical validation requirements

Deployment is **not established**. A staging preparation checklist and Render service settings are documented in [RENDER_STAGING.md](docs/RENDER_STAGING.md). Before any clinical pilot, complete security threat modeling and penetration testing, privacy/legal review, identity and access controls, validated hosting/backup/recovery, operational monitoring, FHIR/SMART conformance and partner testing, and migration rehearsals. Clinical validation requires an approved intended-use statement, independently reviewed source evidence and rule provenance, multidisciplinary review of every rule and override pathway, representative retrospective and prospective evaluation, false positive/negative analysis, subgroup and data-quality analysis, usability and human-factors testing, incident handling, change control, and governance approval. Document evidence and limitations; do not imply clinical validation from software tests.
