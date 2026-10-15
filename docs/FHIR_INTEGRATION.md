# FHIR integration

The backend FHIR adapter is versioned at `app/interop/fhir/adapter.py` (`1.0.0`). The server flow is FHIR server → SMART authorization → adapter → structural validation → normalization → canonical internal data → safety engine. `POST /api/v1/fhir/analyze` accepts a Bundle and follows the same validation and normalization path. Invalid resources return HTTP 422 with resource type, path, and a readable issue; no external resource is analyzed before validation. React components do not parse or map FHIR.

Only explicitly mapped fields are emitted. A field absent from a resource stays `null` or `NOT_AVAILABLE`; the adapter does not invent identifiers or code displays. Medication names are normalized through the configured terminology service and are eligible for medication safety checks only after a confident normalized result. This adapter does not claim complete FHIR conformance.

| R4 resource | Mapped fields | Status |
|---|---|---|
| Patient | id, gender, birthDate, presence of identifier | Partial (implemented fields): identifier values and names are not exposed to analysis |
| AllergyIntolerance | id, code display, clinicalStatus display, verificationStatus display, Patient subject id | Partial (implemented fields): reactions, criticality, onset and category not mapped |
| Condition | id, code display, clinicalStatus display, verificationStatus display, Patient subject id | Partial (implemented fields): stage, severity, body site and encounter linkage not mapped |
| Medication | id, code display/coding, terminology normalization | Partial (implemented fields): ingredient, form and strength not mapped |
| MedicationRequest | id, status, intent, medication[x], subject, dosage text/quantity/unit, authoredOn | Partial (implemented fields): timing, dispense, substitution and requester not mapped |
| MedicationStatement | id, status, medication[x], subject and dosage text/quantity/unit | Partial (implemented fields): adherence/detail and effective period not mapped |
| Observation | id, status, code display, supported value[x], effective time/period, subject | Partial (implemented fields): components, interpretation, reference range and units beyond value[x] are not mapped |
| Encounter | id, status, class, type, period, Patient subject id | Partial (implemented fields): participants, locations, diagnoses and hospitalization details not mapped |

## SMART configuration

Set `FHIR_BASE_URL`, `FHIR_CLIENT_ID`, optional confidential-client `FHIR_CLIENT_SECRET`, and `FHIR_SCOPES` in the server environment. Set `FHIR_REDIRECT_URI` to the registered callback URL. Never put credentials in source, frontend bundles, URLs, or logs. SMART discovery reads `/.well-known/smart-configuration`. The authorization-code flow uses one-time state and PKCE S256, requests the configured scopes (default includes patient launch context, `openid`, `fhirUser`, `offline_access`, patient read scopes and practitioner read), exchanges and refreshes tokens server-side, and never returns token values. It records patient context from the token response and only reports practitioner context when an explicit Practitioner `fhirUser` is provided. Expired tokens without a refresh token require re-authentication. `GET /api/v1/fhir/smart/patient-context` fetches only the authorized Patient `$everything` context and validates it before normalization.

The current SMART token store is process memory for this prototype. It is not durable across restarts and is unsuitable for multiple workers; deployments requiring those properties need an encrypted shared token store. Upstream errors are returned as generic messages without response bodies or credentials. Configure TLS at the FHIR server and deployment boundary.

## Freshness and unavailable context

`FHIR_CONTEXT_MAX_AGE_HOURS` defaults to 24. The analysis `data_quality.fhir_context` output reports `CURRENT`, `STALE`, `UNKNOWN`, or `UNAVAILABLE`, with the newest resource `meta.lastUpdated` when available. A missing timestamp is `UNKNOWN`; an empty/unavailable bundle is `UNAVAILABLE`. `analysis_status` is `INCOMPLETE` if context freshness or medication normalization is not confirmed. Missing Observation values are separately marked `NOT_AVAILABLE`.

The adapter is isolated from the safety engine and can be extended by a separate jurisdiction adapter implementing the same canonical contract. This is modularity preparation only; no India or ABDM compliance is claimed. Imports in the decision path come from configured FHIR servers or supplied bundles, never web scraping. The adapter tests use synthetic data; no real patient data is included.

## Verification status

**Overall status: partial; not clinically validated.** The adapter structure and bounded field mappings are implemented as documented above. The listed field mappings are partial because only the named fields are mapped; omitted fields are not inferred. Structural validation, canonical normalization, freshness reporting, and synthetic tests are implemented. Live sandbox testing, conformance testing against a named server, comprehensive FHIR version coverage, and production-grade token storage are planned. These integration tests do not establish clinical validity.
