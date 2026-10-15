# MediSafe AI: workflow overview

Use this as a product walkthrough outline. Do not load demo records into the running application. Synthetic patient and alert records belong to the frontend test fixtures and backend tests only.

## 1. Product scope

MediSafe AI is a production-oriented clinical decision support prototype. A permanent clinical-use disclaimer remains visible. Analyses report evaluated and unavailable domains; a result with no alerts is not a safety conclusion.

## 2. Normal workflow

1. Sign in with an organization API credential and clinician identity. The browser keeps the credential in memory and clears it on sign out or reload.
2. Search the organization patient list or register a patient.
3. Open the patient profile and review the Summary, Demographics, Allergies, Conditions, Current Meds, Medication History, Observations, Encounters, Prescriptions, Safety Analysis, and Audit tabs. Unconnected record types are labelled unavailable.
4. Create a structured prescription for the selected patient. Required fields are validated before submission.
5. Review terminology normalization and confirm the matched medication with a permitted clinician role.
6. Run analysis. The result reports status, checked and unchecked safety domains, data quality, rule version, and knowledge version.
7. Review alert explanations and record review, acknowledgement, resolution, dismissal, or a structured override when permitted.

## 3. Engineering notes

- The safety engine uses configured, versioned knowledge data. Version 1 remains prototype data pending appropriate clinical review.
- FHIR mapping and SMART authorization are isolated in the backend interop adapter. The current mappings are partial and described in `docs/FHIR_INTEGRATION.md`.
- Rule changes use the governed, reviewable, reversible knowledge process. Clinician feedback does not directly change rules.
- Frontend behavior is covered by synthetic interaction tests; backend behavior is covered by its pytest suite.

This overview makes no claims of clinical validation, regulatory clearance, or deployment readiness.
