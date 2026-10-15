# Clinical safety and validation

MediSafe AI is a **production-oriented clinical decision support prototype** and is **not clinically validated**. It is not a diagnosis or prescribing authority. Do not use its output as a substitute for clinician judgment or validated clinical references.

## Current safety behavior

| Capability | Status | Limitation |
|---|---|---|
| Structured medication entry and normalization review | Partial | Catalog coverage and codes are limited; uncertain entries must not be treated as matched |
| Deterministic rule evaluation | Partial / not clinically validated | Limited prototype rules and incomplete clinical domains |
| Explicit checked/unchecked domains and data quality | Implemented / partial | Data availability is constrained by implemented APIs and submitted context |
| Versioned rule/knowledge traceability | Partial | Version fields are persisted; source evidence needs independent review |
| Alert review, acknowledge, override, resolve, dismiss | Implemented | Decisions are separate records; operating procedures are not established |
| Severe/critical override reason | Implemented | Structured reason enum is required; free text is optional |
| Feedback isolation from rules | Implemented | Feedback supports analytics and review queues only |
| Clinical outcome monitoring | Planned | No validated outcome dataset or monitoring protocol |

## Analysis interpretation

`COMPLETE`, `PARTIALLY_EVALUATED`, `INCOMPLETE`, and `FAILED` describe execution and data coverage; they do not express patient safety. Every analysis should identify checked and unchecked domains. Missing, stale, unknown, unavailable, or unnormalized context is not a negative finding. “No alerts” does not mean “safe.” The interface must not label a patient or order safe.

Rules are deterministic and versioned. Parsing/normalization can assist data entry but must be schema validated and confirmed by a clinician before analysis. Analysis stores the knowledge/rule version used. A failed knowledge lookup or analysis path must not silently return an empty alert set as a successful assessment.

## Knowledge governance

Knowledge is file/trusted-source imported through import, validation, normalization, versioning, clinical review, activation, and audit. A reviewer role is required to activate; rollback is versioned and audited. The existing version 1 data remains labeled “prototype data — not clinically reviewed” until a qualified reviewer signs off. Feedback does not update rules. Any rule change requires the versioned, reviewable, reversible process documented for Stage 6.

Each rule needs a stable identifier and version, source and source version, effective date, evidence reference, severity, trigger conditions, rationale, recommendation, and status. Missing evidence means the domain is not evaluated; do not invent contraindications, interactions, dose limits, or terminology identifiers.

## Review and overrides

An alert is immutable clinical output from an analysis snapshot. Review, acknowledgement, override, resolve, and dismiss actions create separate decision records and audit entries, including rule and knowledge versions. Severe and critical overrides require a structured enum reason and may include explanatory text. These controls preserve review history; they do not prove a decision was clinically correct.

## Required validation before clinical evaluation

1. Define intended use, users, patient population, care setting, excluded use, and risk classification with clinical and regulatory stakeholders.
2. Have independent pharmacists and clinicians verify every knowledge source, rule trigger, severity, rationale, and recommendation; sign and date version 1 or replace it with reviewed evidence.
3. Establish a representative, governed reference dataset and protocol. Evaluate sensitivity, specificity, false alerts, missed hazards, subgroup behavior, missing-data behavior, and confidence/normalization failures.
4. Conduct retrospective and prospective workflow evaluation with clinician adjudication; test interruption burden, alert fatigue, override reasons, and usability.
5. Validate FHIR mappings, provenance, stale-context handling, and identity context against the actual target systems.
6. Establish change control, rollback drills, incident reporting, audit review, post-deployment monitoring, and periodic revalidation.

Passing unit tests or a synthetic demonstration is software verification only. It is not clinical validation evidence.
