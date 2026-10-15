# AGENTS.md — MediSafe AI

## Project status wording (mandatory everywhere: UI, docs, README)
This is a "production-oriented clinical decision support prototype".
NEVER write: clinically validated, FDA-cleared/approved, CE-marked, medical-grade,
HIPAA-compliant, ABDM-certified, hospital-ready. A visible clinical-use disclaimer
stays in the UI until real validation evidence exists. Remove demo behavior, NOT
safety transparency.

## Non-negotiable safety rules
1. Missing/unknown data is NEVER treated as normal or safe. Represent unknown
   explicitly (null + status "unknown" / "not_available"), never as false/0/"".
2. "No alerts" never means "safe". Every analysis reports which safety domains
   were checked and which were not.
3. System failure (DB, knowledge base, normalizer, parser, FHIR) must produce
   analysis status INCOMPLETE or FAILED, never an empty "no alerts" result.
4. Final safety decisions come only from deterministic, versioned, traceable rules.
   LLM/NLP may only parse or normalize input; its output must be schema-validated,
   shown to the clinician for confirmation, and logged with model/version.
5. Do NOT invent clinical facts, interaction pairs, dose limits, or identifiers
   (RxNorm codes etc.). If reference data is missing, the check reports
   "reference data unavailable" and is marked not evaluated.
6. Every clinical rule has: rule_id, version, source, source_version,
   effective_date, evidence_reference, severity, trigger_conditions, rationale,
   recommendation, status.
7. Alerts never change medications automatically. Clinician acknowledges/overrides;
   severe alerts require a structured override reason; original alert is preserved.
8. Use precise wording: "Potential drug-drug interaction detected",
   "Configured contraindication rule matched", "Dose verification required",
   "Insufficient data to evaluate", "Medication could not be confidently normalized".
9. Risk score is a "Rule-Based Alert Priority Score", never a clinical probability.

## Security/privacy rules
- Enforce auth + RBAC on the backend (ADMIN, DOCTOR, PHARMACIST,
  CLINICAL_REVIEWER, READ_ONLY). Frontend hiding is not security.
- No secrets in code or git. Config via env vars; .env.example only with placeholders.
- No PHI (names, phone, email, address, clinical details, tokens) in application
  or security logs. Audit events reference IDs, not duplicated PHI.
- Only explicitly synthetic data (e.g. "Synthetic Test Patient", MRN-TEST-001),
  clearly labelled, in tests/fixtures only.

## Engineering rules
- Inspect before changing. Preserve working safety logic and passing tests.
- No unnecessary rewrites. Update backend + frontend callers + tests together.
- Migrations must not destroy existing data (use Alembic or the project's tool).
- Windows environment. Repo path contains a space:
  "C:\Users\Saurav Shah\medisafe-ai_ML" — always quote paths. Use PowerShell syntax.
- Only use file names/commands that actually exist; verify before referencing.
- After each stage: run tests, fix what you broke, run `git diff --check`,
  and append a summary to docs/PROGRESS.md (done / partial / not done, honestly).
- If something cannot be done, say so in PROGRESS.md. Never claim completion
  for unverified work.


  