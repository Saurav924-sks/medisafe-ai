# MediSafe AI Repository Audit

**Audit date:** 2026-09-30  
**Scope:** Project-owned configuration, frontend source, backend Python, tests, scripts, rule JSON, Docker files, documentation, and available database schema. This is an inspection artifact, not a clinical or security certification.

**Baseline note:** Sections describing the original database and startup behavior record the pre-normalization state as observed on the audit date. The normalized schema and Alembic migration added afterward are documented in [DATA_MODEL.md](DATA_MODEL.md); this file is retained as a dated audit baseline, not the current schema specification.

The project root is `medisafe-ai_ML/`. There is no repository `.git` directory in this workspace copy, so tracked/untracked status and history could not be verified. The root `README.md`, `run_full_stack.py`, `docs/`, SQL files, and seed scripts are absent. A root `.env` exists; its credential values are intentionally not copied here. Runtime/build artifacts (`node_modules`, `dist`, caches, images, and SQLite row contents) are not source; the SQLite schemas were inspected read-only.

## 1. Current Architecture

- **Frontend:** React 19 + Vite, mounted from `frontend/src/main.jsx`; the single main workflow is implemented in `App.jsx`. `WarningCard` renders explanations and feedback controls; `LearningDashboard` loads global feedback statistics and requests reevaluation.
- **API client:** `frontend/src/services/api.js` uses a fixed `http://localhost:8000/api/v1` URL and wraps patient, analysis, feedback, FHIR, and status requests.
- **Backend:** FastAPI in `frontend/backend/main.py`; routes are in `app/api/routes.py`; SQLAlchemy models and services are imported directly by route handlers.
- **Persistence:** SQLAlchemy engine from environment configuration; Docker Compose provisions PostgreSQL. Tests override persistence with in-memory SQLite. Two ignored SQLite files also exist in `frontend/backend/`; the current `.env` config points to Compose host `db`, not either local SQLite file.
- **Rules/data:** A process-global NetworkX graph is loaded by `app/services/knowledge_graph.py` from `frontend/knowledge_base/drug_knowledge.json`. RxNorm and openFDA services provide a best-effort remote fallback for otherwise unmatched drug pairs.
- **Startup/migrations:** Importing `main.py` creates missing tables and runs one custom feedback-column migration. There is no SQL/seed migration directory or Alembic environment, despite Alembic being a dependency.
- **Containers:** Compose defines PostgreSQL, Python 3.11 backend, and a static Nginx frontend. The frontend build currently fails (see section 12).

## 2. Patient-Data Flow

1. The browser creates a patient using `POST /patients`, with literal demo name `John Doe`, age, and gender. Add-allergy, add-condition, and add-medication controls issue separate unauthenticated POSTs.
2. FastAPI validates basic lengths/ranges with Pydantic, creates SQLAlchemy rows, and commits each action individually. The profile is returned without a clinician identity or ownership boundary.
3. Analysis fetches the patient and its allergy, condition, and current-medication relationships. Only those names are passed to the safety engine; age, gender, current-medication dose/frequency, provenance, and completeness are omitted.
4. Prescription raw text and parsed items are persisted. Raw text may contain patient identifiers or clinical details. Alerts and the analysis result itself are not persisted; history later reconstructs inputs and feedback only.
5. Audit middleware records selected request metadata after handling: fixed demo user ID, method/path, query parameters, status, and client IP. It does not record authenticated identity and can include patient IDs or query-string data.

## 3. Prescription-Analysis Flow

`App.jsx` sends `{patient_id, raw_text, items: []}` to `analyzePrescription`. The API client adds its client-visible demo key. FastAPI validates the request, loads the patient profile, then calls `parse_prescription` for non-empty text or maps supplied item fields directly. The route commits a prescription row and item rows before analysis. It calls the deterministic safety engine, severity-sorts raw alerts, calculates the rule-based prototype score, builds explanations, and returns the ID, score, level, alert count, disclaimer, alerts, and breakdown. The browser displays the result and a green “appears safe” state for an empty alert array.

Important boundary: an unrecognized drug is represented as a parser error item, not a failed/incomplete analysis. The route discards that item when saving; the safety engine extracts no drug from it; the scorer returns 0/Low with no alerts. The API response has no analysis status or checked/not-checked domains.

## 4. Safety-Rule Flow

- The graph loads drug nodes and edges from `drug_knowledge.json`. Local checks cover selected drug-drug pairs, drug-disease pairs, and allergy cross-reactivity. Interaction edges are made bidirectional; disease/allergy edges are directional.
- Drug-drug misses call RxNorm approximate-term lookup for both names, then inspect openFDA label text for a substring mention. A mention is tagged informational and explicitly says it is not a verified pairwise interaction. Network/API failures become no lookup result, and the engine emits no “not evaluated” status.
- The engine also detects exact duplicate medications, same-class drugs only among the *new* prescription items, and a narrow dose bound. Dose checks compare one parsed numeric `mg` value with a stored maximum; they do not calculate daily exposure from frequency/duration, normalize units, or account for patient-specific variables.
- Unknown/missing dose data is skipped when dose or name is absent. A numeric dose for a drug without a loaded maximum gets an informational “Dosage Verification” alert; absence of the dose itself does not.
- Score points are fixed by severity (critical 40, high 25, moderate 15, low 5, informational 0), summed and capped at 100. This is not a probability. Feedback reevaluation can halve points for disputed alert types but does not change deterministic alert severity.
- Rule records do not carry the mandated rule ID/version, source version, effective date, evidence reference, trigger conditions, recommendation, or lifecycle status. The checked domains and reference-data versions are not returned.

## 5. Current DB Model

Models are declared in `frontend/backend/app/models/models.py` and `app/models/audit.py`. The local SQLite schemas contain these eight tables. In the list below, `PK`, `FK`, `NULL`, and `DEFAULT` reflect model declarations; SQLAlchemy columns generally remain nullable unless marked otherwise.

| Table | Columns | Constraints / notes |
|---|---|---|
| `patients` | `id`, `name`, `age`, `gender` | `id` primary key; `name` indexed. No unique/check constraints. |
| `patient_allergies` | `id`, `patient_id`, `allergy_name` | PK; nullable FK to `patients.id`; allergy name indexed. |
| `patient_conditions` | `id`, `patient_id`, `condition_name` | PK; nullable FK to `patients.id`; condition name indexed. |
| `patient_medications` | `id`, `patient_id`, `medication_name`, `dose`, `frequency` | PK; nullable FK; name indexed; dose/frequency nullable. |
| `prescriptions` | `id`, `patient_id`, `raw_text`, `created_at` | PK; nullable FK; raw text nullable; `created_at` is a nullable string with no model default and is not set by the route. |
| `prescription_items` | `id`, `prescription_id`, `drug_name`, `dose`, `unit`, `frequency`, `duration` | PK; nullable FK; `drug_name` indexed; other details nullable. |
| `alert_feedback` | `id`, `analysis_id`, `alert_index`, `alert_type`, `drug_name`, `override_decision`, `clinician_note`, `created_at` | PK; `analysis_id` indexed FK to prescriptions with `ON DELETE CASCADE`; `alert_index` non-null; feedback values otherwise nullable; timestamp server default. No uniqueness tying feedback to an actual alert. |
| `audit_logs` | `id`, `timestamp`, `user_id`, `action`, `resource_type`, `resource_id`, `details`, `ip_address` | PK; timestamp server default; user/action indexed; no FK, immutability, or retention constraint. |

No explicit SQL `CHECK` or `UNIQUE` constraints are declared. Patient and prescription ORM relationships cascade deletes, but corresponding FK nullability is permissive. SQLite FK enforcement depends on connection configuration. Both local DB files have the legacy schema without `alert_type` and `drug_name` in `alert_feedback`; startup adds them with empty-string defaults. The migration is hand-written and not versioned.

## 6. Current API Routes

`/` and `/api/health` are defined in `main.py`; other paths are under `/api/v1`.

| Method + path | API key required? | Behavior |
|---|---|---|
| `GET /` | No | Welcome and Swagger path. |
| `GET /api/health` | No | Returns static healthy/connected values; does not check DB. |
| `POST /api/v1/patients` | No | Create patient. |
| `GET /api/v1/patients` | No | List all patients. |
| `GET /api/v1/patients/{patient_id}` | No | Read patient profile. |
| `POST /api/v1/patients/{patient_id}/allergies` | No | Add allergy. |
| `POST /api/v1/patients/{patient_id}/conditions` | No | Add condition. |
| `POST /api/v1/patients/{patient_id}/medications` | No | Add medication. |
| `POST /api/v1/prescriptions/analyze` | Yes | Persist inputs and run analysis. |
| `POST /api/v1/prescriptions/analyze/{analysis_id}/feedback` | Yes | Persist caller-supplied feedback. |
| `GET /api/v1/prescriptions/analyze/{analysis_id}` | No | Return raw text, items, and feedback. |
| `GET /api/v1/feedback/analytics` | No | Return feedback aggregates across the database. |
| `POST /api/v1/prescriptions/analyze/{analysis_id}/reevaluate` | Yes | Recompute alerts with global feedback point adjustments. |
| `POST /api/v1/fhir/analyze` | Yes | Parse limited patient context and analyze a fixed Warfarin prescription. |
| `GET /api/v1/system/status` | No | DB probe; external service/NLP indicators are constants. |

The key is a shared static header check, not authentication or authorization. Patient CRUD, list, history, analytics, health, and status routes have no API-key dependency. Route definitions: [routes.py](../frontend/backend/app/api/routes.py) and [main.py](../frontend/backend/main.py).

## 7. Frontend Workflow

- No patient is selected initially. “Happy-Path” and “High-Risk” buttons create new `John Doe` records; the high-risk profile is not pre-populated and requires manual allergy/condition/medication entry.
- The user enters free text, runs analysis, then sees a score, alerts, evidence, and recommended actions. There is no form-level max text validation, parser-confirmation step, completeness checklist, or “incomplete/not evaluated” state.
- Patient write handlers update local UI state after any JSON response, without checking HTTP status. Failures can therefore appear as successful local additions.
- “View History” only changes unused state; no history modal/view is rendered. Learning analytics catches errors but leaves the dashboard in its loading state. The refresh spinner state is never set.
- The header defaults NLP and KG status to “Operational”; the API status endpoint does not report a KG field. Empty alerts render as green and state that the prescription appears safe.

## 8. Demo-Only Code

- Hard-coded `John Doe` name and 45/65-year-old profiles: [App.jsx](../frontend/src/App.jsx); duplicated test fixture: [test_demo_scenarios.py](../frontend/backend/tests/test_demo_scenarios.py).
- Demo happy/pathological scenarios and prose claims (“healthy,” “safe,” “zero AI hallucinations,” “ready to assist”) in [DEMO_SCRIPT.md](../DEMO_SCRIPT.md). Those claims exceed the implementation and conflict with prototype disclaimers elsewhere.
- Hard-coded demo API key in the browser client and tests; default/fallback demo key in backend config/security. A value in a browser bundle is public regardless of the server-side check.
- FHIR route analyzes a fixed Warfarin 5 mg item irrespective of submitted `MedicationRequest` content.
- Hard-coded system name/version and “Operational” service strings; fixed audit `system_demo_user`.
- Script-style self-improvement demo with an absolute `C:/Windows/System32/...` path and fixed key: `frontend/backend/test_self_improvement.py`. `run_self_improvement_flow.py` uses a similarly fixed path and attempts to kill matching Python processes; it was not run.
- Rule JSON is synthetic/demo-scale input but is not labelled by runtime provenance; there is no SQL seed dataset. Test fixtures use “John Doe” rather than the required explicitly synthetic test identity.
- `.env.example` is absent. `.env` is ignored by `.gitignore`, but the workspace has no Git metadata, so whether it is tracked elsewhere cannot be established.

## 9. Security Risks

1. **No backend identity/RBAC:** Shared API key, no user identity, roles, patient ownership checks, or per-record authorization. Most patient/PHI reads and writes do not require the key.
2. **Client-exposed credential:** Static key is embedded in `frontend/src/services/api.js`; it is not a meaningful authorization boundary. `SECRET_KEY` is configured but unused for signed sessions/tokens.
3. **Sensitive data exposure:** Patient lists and analysis history are unauthenticated. Raw prescription text and clinician notes are persisted without retention controls, field-level minimization, encryption policy, or PHI-safe logging guarantees.
4. **Audit shortcomings:** Fixed identity, mutable database rows, IP/path/query metadata, no integrity controls, no retention policy; failed audit writes are logged and do not block operations.
5. **Configuration/deployment:** Development defaults remain in backend config; `.env` includes populated DB/security settings; no `.env.example`. Compose publishes PostgreSQL on host port 5432; no TLS/reverse-proxy/auth layer is configured. Local backend startup using `.env` host `db` will not resolve unless run in Compose.
6. **CORS/status:** CORS permits wildcard methods/headers with credentials for two localhost origins; health is always green; service status is hard-coded. Neither status surface is a trustworthy operational readiness check.
7. **Input/error handling:** Patient-side API helpers do not reject non-2xx responses. Remote-service errors are printed, not surfaced as incomplete analysis. No per-user request rate limiting or abuse controls are visible.

## 10. Clinical-Safety Limitations

- This is not clinically validated. Local knowledge is incomplete and not clinically governed; no independent provenance/version/effective-date lifecycle exists. `drug_interactions.json` and `drug_disease.json` are not loaded by the graph, while `drug_knowledge.json` contains only a small subset. The `dose_limits` and `duplicate_therapeutic_classes` collections in the separate `drug_interactions.json` file are not loaded or consumed.
- The scorer is a severity-point sum, not risk probability or calibrated clinical score. Feedback can globally down-weight point contributions after three disagreements; it is not validated learning and is not isolated by patient, institution, role, rule version, or feedback quality.
- Medication parsing uses fuzzy string matching and regex. spaCy is loaded/downloaded but its NLP pipeline is not used. No clinician confirmation/schema review of parse results exists. Frequency and duration are extracted but not used for dose totals.
- Dose limits are simplistic, only apply for loaded values and `mg`, and lack age/weight/renal/hepatic/pregnancy/indication context. Current patient age/gender are not passed to rules. No lab values, route, formulation, timing, or administration context are modeled.
- Exact string matching means aliases, spelling variants, code systems, and normalization uncertainty can miss a rule. RxNorm approximate-term first-candidate matching is not confirmed by a clinician; external lookup is not required to succeed. openFDA label text mention is not pairwise evidence.
- FHIR support is a partial text-only Bundle parser, without profiles, codings, references, statuses, patient linkage, terminology validation, or incoming-prescription mapping.
- There is no structured override workflow, severe-alert override reason requirement, rule-level traceability, checked-domain report, or durable analysis result snapshot. Recommendations can be categorical (“DO NOT DISPENSE”) despite rule coverage limits.

## 11. Missing Data Treated as Safe/Normal

These are concrete fail-open or falsely reassuring paths; “no alert” here means only that no configured rule emitted an alert, not that the prescription is safe.

| Missing/unknown input or failure | Current behavior | Source |
|---|---|---|
| Missing profile arrays | Missing allergies, conditions, or current medications default to empty lists; all relevant checks run as though no records exist. | [safety_engine.py#L15](../frontend/backend/app/services/safety_engine.py#L15), [safety_engine.py#L16](../frontend/backend/app/services/safety_engine.py#L16), [safety_engine.py#L17](../frontend/backend/app/services/safety_engine.py#L17) |
| No recognized drug in text | Parser returns an error object; route excludes it from persisted items and the engine filters it out. Analysis still scores empty alerts as 0/Low. | [nlp_parser.py#L85](../frontend/backend/app/services/nlp_parser.py#L85), [routes.py#L114](../frontend/backend/app/api/routes.py#L114), [safety_engine.py#L20](../frontend/backend/app/services/safety_engine.py#L20), [risk_scorer.py#L44](../frontend/backend/app/services/risk_scorer.py#L44) |
| Missing drug or dose | Dose checking silently continues; no “insufficient data” alert or analysis status is created. | [safety_engine.py#L132](../frontend/backend/app/services/safety_engine.py#L132) |
| Dose has no loaded limit | An informational verification alert is emitted only when drug and dose exist; it adds zero score points and does not make analysis incomplete. | [safety_engine.py#L156](../frontend/backend/app/services/safety_engine.py#L156), [risk_scorer.py#L9](../frontend/backend/app/services/risk_scorer.py#L9) |
| Unknown/missing severity | Explanations and scoring default to informational; unknown severity maps to zero points. | [explainability_engine.py#L11](../frontend/backend/app/services/explainability_engine.py#L11), [risk_scorer.py#L30](../frontend/backend/app/services/risk_scorer.py#L30) |
| Rule graph miss | Unmatched pair/disease/allergy returns `None`; no explicit “reference unavailable/not evaluated” signal. Exact missing edge is indistinguishable from a negative rule result. | [knowledge_graph.py#L102](../frontend/backend/app/services/knowledge_graph.py#L102), [knowledge_graph.py#L110](../frontend/backend/app/services/knowledge_graph.py#L110), [knowledge_graph.py#L118](../frontend/backend/app/services/knowledge_graph.py#L118) |
| RxNorm unavailable/no candidate | Cached `None` is returned; graph fallback is skipped and no alert/status indicates failed normalization. | [rxnorm_service.py#L36](../frontend/backend/app/services/rxnorm_service.py#L36), [rxnorm_service.py#L40](../frontend/backend/app/services/rxnorm_service.py#L40) |
| openFDA missing label/network/error/no section | Returns an empty list; interaction check returns no match, indistinguishable from a completed negative lookup. | [openfda_service.py#L19](../frontend/backend/app/services/openfda_service.py#L19), [openfda_service.py#L57](../frontend/backend/app/services/openfda_service.py#L57), [openfda_service.py#L61](../frontend/backend/app/services/openfda_service.py#L61) |
| Missing/empty FHIR `entry` | Parser returns a profile with all domains empty; endpoint can still return a successful analysis of its fixed Warfarin prescription. | [fhir_parser.py#L12](../frontend/backend/app/services/fhir_parser.py#L12), [fhir_parser.py#L17](../frontend/backend/app/services/fhir_parser.py#L17), [routes.py#L360](../frontend/backend/app/api/routes.py#L360) |
| Missing FHIR text fields | Fabricated sentinels (“Unknown Allergen/Condition/Med”) or “As prescribed” substitute for missing coding/dose content; these are not marked unknown and often do not match graph rules. | [fhir_parser.py#L26](../frontend/backend/app/services/fhir_parser.py#L26), [fhir_parser.py#L31](../frontend/backend/app/services/fhir_parser.py#L31), [fhir_parser.py#L36](../frontend/backend/app/services/fhir_parser.py#L36), [fhir_parser.py#L39](../frontend/backend/app/services/fhir_parser.py#L39) |
| Empty alert list | UI renders green check, “No safety alerts detected,” and says the prescription “appears safe.” | [App.jsx#L240](../frontend/src/App.jsx#L240), [App.jsx#L241](../frontend/src/App.jsx#L241) |
| Missing status-service field or request failure | Header defaults missing NLP/KG values to “Operational”; `useEffect` swallows status fetch failure without a failed state. | [App.jsx#L23](../frontend/src/App.jsx#L23), [App.jsx#L117](../frontend/src/App.jsx#L117), [App.jsx#L118](../frontend/src/App.jsx#L118) |
| Health probe | `/api/health` always says database connected without probing it. | [main.py#L40](../frontend/backend/main.py#L40), [main.py#L42](../frontend/backend/main.py#L42) |
| System-service indicators | RxNorm, openFDA, and NLP are reported as operational constants, regardless of actual reachability/model/data. | [routes.py#L392](../frontend/backend/app/api/routes.py#L392), [routes.py#L395](../frontend/backend/app/api/routes.py#L395) |
| Missing feedback decision | API schema allows `null`; analyzer’s generic fallback counts falsey/null as disagreement, potentially down-weighting a rule based on no decision. | [schemas.py#L46](../frontend/backend/app/schemas/schemas.py#L46), [feedback_analyzer.py#L76](../frontend/backend/app/services/feedback_analyzer.py#L76) |
| Analytics request failure | Learning dashboard catches the error and retains its loading presentation instead of exposing unavailable/failed status. | [LearningDashboard.jsx#L17](../frontend/src/components/LearningDashboard.jsx#L17), [LearningDashboard.jsx#L19](../frontend/src/components/LearningDashboard.jsx#L19) |

## 12. Existing Bugs, Dead Code, and Duplicated Logic

- **Frontend production build fails:** `LearningDashboard.jsx` imports `./services/api`, but the API client is a sibling of `components/`; Vite cannot resolve the module. `npm run build` exits non-zero.
- **Disagree feedback cannot be submitted from UI:** `WarningCard` sets decision to `false` for Disagree, then disables Submit with `disabled={!feedbackDecision}`. This blocks the disagreement signal required for adaptation.
- **History UI is incomplete/dead:** button only sets `historyOpen`; no modal uses it. `loadLastAnalysis`, history result/loading state, and API history import are otherwise unused.
- **Learning UI dead state:** `refreshing`/setter never changes; `AlertCircle` import is unused. Its API import path is also the build failure.
- **API response handling inconsistent:** patient create/add helpers parse JSON without checking `response.ok`, so the UI may update optimistically after backend rejection. Analysis/history methods do check status.
- **Dose parsing/runtime failure:** `float(dose)` can raise for nonnumeric values; dose calculation ignores frequency/duration and only recognizes `mg`.
- **Duplicate checks incomplete:** same-class duplicate logic only compares new items to each other, not the patient’s current medications. `duplicate_therapeutic_classes` metadata is not used; severity/reason are hard-coded.
- **FHIR semantic mismatch:** incoming MedicationRequest is treated as current context, while the actual new prescription is fixed Warfarin. Missing/malformed fields can be silently replaced or fail parsing.
- **Status is misleading:** health is static; service indicators are static. Frontend supplies “Operational” for absent KG state.
- **History not reproducible:** computed alerts, rule versions, knowledge-base version, parser output confidence, and score result are not stored. `prescriptions.created_at` is not populated.
- **Parser dead code/unused output:** spaCy is loaded but `nlp` is never used; `raw_text_snippet` is produced but discarded by the persistence field allowlist. Several frontend imports/states and the `WarningCard.alertIndex` parameter are unused.
- **Duplicated/stale rule data:** `drug_knowledge.json`, `drug_interactions.json`, and `drug_disease.json` repeat or diverge in content. The latter two are not wired into graph loading; loaded JSON also has fields that the engine ignores. Knowledge is embedded as unversioned JSON, with claims/provenance not verified here.
- **Demo scripts are brittle:** `test_self_improvement.py` executes a client workflow at import time and inserts an unrelated absolute path; `run_self_improvement_flow.py` hardcodes another path and attempts process termination. Neither is in pytest’s collected test set.
- **Package/config drift:** root `package-lock.json` declares a dependency while root `package.json` has no dependencies; frontend uses its own package manifest/lock. Root README/run_full_stack and `.env.example` are absent. No Docker/PostgreSQL integration check exists.

## 13. Existing Test Inventory and Current Results

**Backend pytest:** `frontend/backend/tests/` contains six modules and 11 collected tests: API (3), demo scenarios (2), FHIR (2), knowledge graph fallback (1), safety engine (2), schema migration (1). The top-level `test_self_improvement.py` is not collected. Tests use in-memory SQLite and the demo key; external fallback is mocked in the collected test. No clinical-data completeness, failed dependency, real PostgreSQL, authorization matrix, frontend interaction, or regression test covers the bugs above.

**Run result:** `python -m pytest -q` from `frontend/backend`: **11 passed, 76 deprecation warnings** (Starlette/AnyIO and FastAPI asyncio APIs). `pytest --collect-only` confirmed the 11 test names above.

**Frontend checks:** `npm run lint`: exit 0, **12 warnings** (unused parameters/imports/state and a React immutability warning in `LearningDashboard`). `npm run build`: **failed**, unresolved `./services/api` import from `src/components/LearningDashboard.jsx`.

**Other scripts:** Six `frontend/scripts/test_*.py` scripts are print-oriented smoke/demo scripts, not pytest tests; `test_medical_grade.py` calls live RxNorm/openFDA APIs. They were read but not run because some perform external network requests and provide no isolated deterministic test gate. The two top-level self-improvement scripts were not run; one starts a server and may kill Python processes. No SQL test/seed files were present.

## 14. Files to Modify / Files to Leave Unchanged

At the time this audit was created, it was the only requested addition. The normalized model work is documented in `docs/DATA_MODEL.md` and tracked separately in `docs/PROGRESS.md`.

**Likely future modification areas (after approval and staged tests):**
- Backend API contracts/status: `frontend/backend/app/api/routes.py`, `app/schemas/schemas.py`, `main.py`.
- Safety completeness and deterministic rule provenance: `app/services/safety_engine.py`, `knowledge_graph.py`, `nlp_parser.py`, `risk_scorer.py`, `explainability_engine.py`, RxNorm/openFDA/FHIR services, and the three `frontend/knowledge_base/*.json` files.
- Persistence/versioned migrations: `app/models/models.py`, `app/models/audit.py`, `app/core/database.py`, `app/core/schema_migrations.py`; introduce versioned migrations only after data backup/compatibility plan.
- Security/privacy: `app/core/security.py`, `app/core/config.py`, `app/core/audit_middleware.py`, Compose/Docker configuration, and `.env.example` (new, placeholders only).
- Frontend states/workflows: `frontend/src/App.jsx`, both components, and `frontend/src/services/api.js`.
- Tests should be added/updated with every contract change under `frontend/backend/tests/`; frontend behavior currently lacks automated tests.

**Leave unchanged absent explicit scope/approval:** `AGENTS.md` (project policy), ignored `frontend/backend/*.db` data (never overwrite/drop as a “fix”), `frontend/dist/` generated output, dependency lockfiles unless dependencies actually change, and demo/presentation wording until a separate content review. Existing SQLite DBs should be backed up before any migration or startup that mutates schemas. Do not expose `.env` values in docs/logs.

## 15. Proposed Staged Migration Plan (Risk per Stage)

| Stage | Work and exit criteria | Risk |
|---|---|---|
| 0. Containment and baseline | Keep prototype/non-clinical disclaimer; prohibit real PHI; secure/rotate local secrets outside source; preserve DB backups; establish deterministic test/build baseline. | Low–Medium: configuration changes can break local/Compose startup. |
| 1. Fail-closed analysis contract | Add explicit `COMPLETE`/`INCOMPLETE`/`FAILED`, per-domain `evaluated/not_evaluated`, unknown statuses, reference availability, and parser confirmation; prevent empty/unrecognized input from returning “safe”/0. Add regression tests first. | High: changes safety meaning and frontend/API contract. |
| 2. Rule governance | Decide authoritative knowledge source; remove duplicate ambiguity; version rule records and require source/effective date/evidence/trigger/rationale/recommendation/status; validate graph load and expose exact coverage. | High: rule-content changes can change alerts; require pharmacist/clinical owner approval. |
| 3. Data model and migrations | Add immutable analysis snapshots, parsed-input provenance, rule/data versions, completeness states, and safe audit identifiers; replace startup ad hoc alters with versioned non-destructive migrations; test SQLite and PostgreSQL. | High: patient/analysis history migration and compatibility risk. |
| 4. Authentication, authorization, privacy | Replace shared key with backend identity/RBAC and patient-scoped authorization; remove frontend secrets; restrict routes/CORS; minimize PHI logs, protect audit integrity/retention, configure TLS and secrets. | High: access-control mistakes can disclose or block patient data. |
| 5. Clinical rule and parsing validation | Replace heuristic-only normalization/dose handling with validated terminology/reference workflows; treat model/reference failures as not evaluated; formalize safe units/frequency/context; clinician confirmation for uncertain parses. | Very High: direct effect on alert sensitivity and clinical interpretation. |
| 6. FHIR and external references | Implement profile-validated FHIR ingestion and actual MedicationRequest mapping; test malformed/partial bundles; clearly separate label mention from verified interaction; report outage/coverage status. | High: interoperability and source mismatch can produce silent omissions. |
| 7. Frontend and feedback controls | Fix build and disagreement UI; display incomplete/failed states and unchecked domains; remove demo personas/keys from normal workflow; make history/status truthful; restrict feedback and prevent it from lowering clinical severity without governed review. | Medium–High: workflow changes can alter clinician interpretation; feedback changes remain safety-sensitive. |
| 8. Validation/deployment gate | Independent clinical review, retrospective/synthetic test corpus, sensitivity/false-negative analysis, prospective shadow testing, security/privacy review, and deployment approval before any real-care use. | Very High: evidence-generation and deployment decisions; do not claim completion from software tests alone. |

**Stop condition:** No implementation was performed. This audit is the deliverable; all future stages require a separate authorization and validation cycle.
