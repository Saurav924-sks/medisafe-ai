# Render staging preparation

MediSafe AI remains a **production-oriented clinical decision support prototype**.
This configuration is for synthetic-data staging only. It does not establish
clinical validation, production security, or production readiness.

## Service settings

Create a Render PostgreSQL database and two services. Use the backend database's
**internal** connection URL for the backend only.

| Setting | Backend Web Service | Frontend Static Site |
|---|---|---|
| Root directory | `frontend/backend` | `frontend` |
| Runtime | Python `3.11.9`, pinned in `.python-version` (also set `PYTHON_VERSION=3.11.9`) | Node `22.12.0`, pinned in `.node-version` (also set `NODE_VERSION=22.12.0`) |
| Build command | `pip install -r requirements.txt` | `npm ci && npm run build` |
| Pre-deploy command, if available | `alembic upgrade head` | None |
| Start command | `uvicorn main:app --host 0.0.0.0 --port $PORT` | None (static site) |
| Publish directory | None | `dist` |
| Health check path | `/api/health` | None |

If the selected Render plan does not provide a pre-deploy command, use this
backend start command instead, and keep the staging service to one instance so
multiple instances do not race to apply migrations:

```sh
alembic upgrade head && uvicorn main:app --host 0.0.0.0 --port $PORT
```

Application imports no longer apply migrations. The pre-deploy/start command is
the explicit schema migration step. Alembic reads `DATABASE_URL` through
`migrations/env.py`; no external database was contacted during preparation.

The backend `.python-version` pins Python to `3.11.9`, matching the project's
backend Docker image line and tested local environment. Render selects it from
the file in the service root; set `PYTHON_VERSION=3.11.9` in the backend
environment as an explicit runtime pin as well. The frontend `.node-version` pins Node
`22.12.0`, which meets the installed Vite major's declared engine range
(`^20.19.0 || >=22.12.0`). Set the Render `NODE_VERSION` environment variable
to the same value so the static build runtime is explicit.

## Backend environment

Set these in the backend service environment. Use Render's managed values for
secrets; do not copy local `.env` contents or put secrets in `VITE_*` variables.

| Variable | Requirement |
|---|---|
| `APP_ENV` | Required; set to `staging`. |
| `DATABASE_URL` | Required; use the Render PostgreSQL internal URL. `postgres://` and `postgresql://` are normalized to the installed `psycopg2` driver. Hosted SQLite and implicit local/default DB configuration are rejected. |
| `API_KEY` | Required for API authentication. The current shared organization key and caller-supplied clinician ID are a prototype boundary, not individual authentication. Use synthetic users and rotate this value; do not treat this as production auth. |
| `CORS_ORIGINS` | Required; comma-separated, explicit origin(s), e.g. `https://<frontend-service>.onrender.com`. No paths, wildcard, or request-reflected origins. |
| `PORT` | Supplied by Render; do not hardcode or add it as a secret. |
| `SECRET_KEY` | Configured in the application settings but currently has no application-code consumer. Do not rely on it for auth. If retained, configure a fresh managed value; do not reuse a leaked/local value. |

`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, and `POSTGRES_PORT` are
used only to construct the non-hosted fallback PostgreSQL URL. A hosted process
must supply `DATABASE_URL`; it will not use this fallback. `FHIR_BASE_URL`,
`FHIR_CLIENT_ID`, `FHIR_CLIENT_SECRET`, `FHIR_SCOPES`, `FHIR_REDIRECT_URI`, and
`FHIR_CONTEXT_MAX_AGE_HOURS` are only needed when configuring the optional SMART
FHIR integration. FHIR token state is in memory and is not suitable for
multi-instance use.

## Frontend API URL and CORS

Set frontend build variable `VITE_API_BASE_URL` to the backend's HTTPS origin:

```text
https://<backend-service>.onrender.com
```

The frontend appends `/api/v1`. It also accepts the complete base
`https://<backend-service>.onrender.com/api/v1`; that suffix is not duplicated.
The variable is public build configuration, not a secret. Never set API keys,
database credentials, or signing secrets as Vite variables.

Set backend `CORS_ORIGINS` to the exact frontend origin (scheme and host, with
port if applicable), without a path or trailing slash. Local development
defaults remain `http://localhost:5173,http://localhost:3000`; hosted startup
requires an explicit `CORS_ORIGINS` value.

`GET /api/health` executes `SELECT 1` and returns 503 with a generic disconnected
status if the database is unavailable; use `/api/health` for Render readiness.
`GET /api/v1/system/status` reports database and NLP checks without exposing
connection strings or secret values. A status response is not a clinical safety
assessment.

## Synthetic staging clinicians

The local `seed_dev.py` intentionally refuses PostgreSQL and must not be used to
seed a hosted service. The separate `scripts/seed_staging.py` only inserts the
synthetic organization, required role rows if missing, two clearly synthetic
clinicians, and missing role assignments. It does not create patient data,
reactivate or rewrite existing organization, role, or clinician records, or
activate a knowledge version. It only adds missing expected role assignments
when existing records are consistent. It is not run during app startup.

After a fresh staging database has been migrated, open the backend Render Shell
and set `MEDISAFE_STAGING_DATABASE_NAME` to the exact database name in the Render
internal PostgreSQL URL. Then run this explicitly confirmed command:

```sh
MEDISAFE_STAGING_SEED_CONFIRM=CREATE_SYNTHETIC_STAGING_CLINICIANS python scripts/seed_staging.py
```

The shell must already have `APP_ENV=staging`, the backend's `DATABASE_URL`,
and `MEDISAFE_STAGING_DATABASE_NAME` matching that URL's database component.
The script refuses production, non-staging environments, a missing confirmation,
a mismatched database-name guard, and non-PostgreSQL databases. It prints the
resulting synthetic clinician IDs; the admin/prescriber role assignment is
`ADMIN` plus `DOCTOR`, and the other clinician is `READ_ONLY`. The operation is
idempotent. If an existing synthetic record is inactive or has unexpected
identity fields, it aborts instead of reactivating or rewriting it.

## Security and clinical limitations

The UI sign-in sends one shared API key and a numeric clinician ID. This does
not prove the person entering the ID is that clinician. Before production use,
replace it with an individual identity provider, server-validated sessions,
MFA as appropriate, short-lived credentials, authorization review, and
operational audit controls. Keep synthetic data only in staging. Do not
activate unreviewed knowledge data to make analysis appear complete; analysis
must remain incomplete until an authorized clinical review and activation
workflow is completed. The current rule set is partial, SMART state is
in-memory, and no live FHIR service or clinical validation is established.
