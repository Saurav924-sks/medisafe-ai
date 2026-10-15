# Security and privacy

Status: access checks and basic secret handling are **partial**. Threat modeling, independent penetration testing, production identity controls, and deployment controls are **planned**. No security certification or compliance claim is made.

## Authentication and authorization

Requests use `X-API-Key` plus `X-Clinician-ID`. The key is compared against environment configuration; the backend returns service unavailable if no key is configured and rejects missing/invalid credentials. Clinician identity must resolve to an active user, and route dependencies check roles. Patient and prescription access is organization-scoped. The frontend's role-sensitive controls are convenience only; backend checks are authoritative.

This shared organization credential plus caller-supplied numeric clinician identifier is not strong user authentication. There is no password flow, MFA, identity provider integration, per-user token, or production-grade session. Replace it before any real clinical use. The frontend currently stores the shared credential in tab-scoped `sessionStorage`; this is a prototype convenience, not secure credential management. Avoid putting credentials in URLs, `localStorage`, source control, logs, or crash reports.

## Secrets and configuration

Use environment variables or a managed secret service for `API_KEY`, database credentials, `FHIR_BASE_URL`, `FHIR_CLIENT_ID`, `FHIR_CLIENT_SECRET`, and `FHIR_SCOPES`. `.env.example` contains placeholders. Keep `.env` local and out of version control. Do not reuse test fixture credentials. Backend configuration has no default API or database password. Restrict who can read process environments and deployment configuration.

## Data handling

Use synthetic data in automated tests. Logs and audit metadata must not include patient names, contact details, clinical narratives, API credentials, access/refresh tokens, authorization codes, or PKCE verifiers. Audit events should refer to record identifiers and action metadata. Database encryption, retention, access monitoring, backup encryption, and deletion policy require deployment-level implementation and review.

## API defenses

The backend uses typed request schemas, bounded fields, role checks, and SQLAlchemy parameterized queries. Security tests cover missing/invalid credentials, unknown identities, read-only write attempts, cross-organization reads, injection-shaped text, malformed JSON, and invalid typed prescription values. This is not a substitute for fuzzing, rate limits, CSRF review for cookie-based auth, dependency scanning, or an independent penetration test.

## FHIR and token handling

FHIR secrets come from environment configuration. SMART state and PKCE are checked by the adapter, and access tokens are kept server side, not returned to the browser or written to logs. The token map currently lives in process memory; it is not encrypted/shared, is lost on restart, and is unsuitable for multi-worker production. Token revocation and provider-specific conformance need more work.

## Audit and incident response

Alert decisions are stored as separate records with actor, timestamp, action, reason, rule version, and knowledge version; matching audit events are also recorded. Feedback is isolated from clinical rule records. The audit store is ordinary application database data, not tamper-evident. External append-only export, alerting, incident playbooks, and retention controls are planned.

## Release checklist

Before a governed pilot, document assets and trust boundaries; threat model the API, frontend, DB, and FHIR link; add managed identity/MFA, TLS and secret rotation; constrain DB/service network access; scan dependencies and container images; test backups and restore; define PHI logging and retention policy; run independent penetration and privacy reviews; and verify audit integrity/operations.
