"""FHIR R4 bundle validation and versioned resource mapping."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

FHIR_ADAPTER_VERSION = "1.0.0"
SUPPORTED_RESOURCE_TYPES = (
    "Patient", "AllergyIntolerance", "Condition", "Medication", "MedicationRequest",
    "MedicationStatement", "Observation", "Encounter",
)


class FHIRValidationError(ValueError):
    def __init__(self, issues: list[dict[str, str]]):
        self.issues = issues
        super().__init__("FHIR Bundle validation failed")


def _issue(issues: list[dict[str, str]], entry: int | None, resource_type: str, path: str, message: str) -> None:
    issue = {"resource_type": resource_type, "path": path, "message": message}
    if entry is not None:
        issue["entry"] = str(entry)
    issues.append(issue)


def _is_object(value: Any) -> bool:
    return isinstance(value, dict)


def _coded_display(value: Any) -> str | None:
    if not _is_object(value):
        return None
    text = value.get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()
    codings = value.get("coding")
    if isinstance(codings, list):
        for coding in codings:
            if _is_object(coding) and isinstance(coding.get("display"), str) and coding["display"].strip():
                return coding["display"].strip()
    return None


def _validate_resource(resource: Any, index: int, issues: list[dict[str, str]]) -> None:
    if not _is_object(resource):
        _issue(issues, index, "Unknown", "resource", "Resource must be a JSON object.")
        return
    resource_type = resource.get("resourceType")
    if not isinstance(resource_type, str) or not resource_type:
        _issue(issues, index, "Unknown", "resource.resourceType", "resourceType is required.")
        return
    if resource_type not in SUPPORTED_RESOURCE_TYPES:
        _issue(issues, index, resource_type, "resource.resourceType", "Resource type is not supported by this adapter version.")
        return
    if not isinstance(resource.get("id"), str) or not resource["id"].strip():
        _issue(issues, index, resource_type, "resource.id", "A resource id is required for bundle mapping.")

    if resource_type in {"AllergyIntolerance", "Condition", "Medication", "Observation"}:
        field = "code"
        if not _is_object(resource.get(field)):
            _issue(issues, index, resource_type, f"resource.{field}", f"{field} must be a CodeableConcept object.")
        elif not _coded_display(resource[field]):
            codings = resource[field].get("coding", [])
            if not isinstance(codings, list) or not any(_is_object(item) and item.get("code") and item.get("system") for item in codings):
                _issue(issues, index, resource_type, f"resource.{field}", "Provide text or a coding with system and code; no display name can be inferred.")

    if resource_type in {"MedicationRequest", "MedicationStatement"}:
        status = resource.get("status")
        allowed_statuses = {
            "MedicationRequest": {"active", "on-hold", "cancelled", "completed", "entered-in-error", "stopped", "draft", "unknown"},
            "MedicationStatement": {"active", "completed", "not-taken", "on-hold", "unknown", "entered-in-error", "intended"},
        }
        if not isinstance(status, str) or status not in allowed_statuses[resource_type]:
            _issue(issues, index, resource_type, "resource.status", "status is missing or unsupported.")
        if not (_is_object(resource.get("medicationCodeableConcept")) or _is_object(resource.get("medicationReference"))):
            _issue(issues, index, resource_type, "resource.medication[x]", "Provide medicationCodeableConcept or medicationReference.")
        subject = resource.get("subject")
        if not _is_object(subject) or not isinstance(subject.get("reference"), str) or not subject["reference"].startswith("Patient/"):
            _issue(issues, index, resource_type, "resource.subject.reference", "A subject reference is required.")

    if resource_type in {"AllergyIntolerance", "Condition", "Observation", "Encounter"}:
        subject = resource.get("patient") if resource_type == "AllergyIntolerance" else resource.get("subject")
        if not _is_object(subject) or not isinstance(subject.get("reference"), str) or not subject["reference"].startswith("Patient/"):
            _issue(issues, index, resource_type, "resource.patient.reference" if resource_type == "AllergyIntolerance" else "resource.subject.reference", "A Patient reference is required for patient-scoped analysis.")

    if resource_type == "MedicationRequest" and isinstance(resource.get("intent"), str):
        allowed_intents = {"proposal", "plan", "order", "original-order", "reflex-order", "filler-order", "instance-order", "option"}
        if resource["intent"] not in allowed_intents:
            _issue(issues, index, resource_type, "resource.intent", "intent is unsupported.")
    if resource_type == "MedicationRequest":
        instructions = resource.get("dosageInstruction", [])
        if not isinstance(instructions, list) or any(not _is_object(item) for item in instructions):
            _issue(issues, index, resource_type, "resource.dosageInstruction", "dosageInstruction must be an array of objects.")
        elif any(not isinstance(item.get("doseAndRate", []), list) or any(not _is_object(rate) for rate in item.get("doseAndRate", [])) for item in instructions):
            _issue(issues, index, resource_type, "resource.dosageInstruction.doseAndRate", "doseAndRate must be an array of objects.")

    if resource_type == "MedicationRequest" and not isinstance(resource.get("intent"), str):
        _issue(issues, index, resource_type, "resource.intent", "intent is required.")
    if resource_type == "Observation":
        status = resource.get("status")
        if not isinstance(status, str) or status not in {"registered", "preliminary", "final", "amended", "corrected", "cancelled", "entered-in-error", "unknown"}:
            _issue(issues, index, resource_type, "resource.status", "status is missing or unsupported.")
    if resource_type == "Encounter":
        if not isinstance(resource.get("status"), str) or resource["status"] not in {"planned", "in-progress", "on-hold", "discharged", "finished", "cancelled", "discontinued", "entered-in-error", "unknown"}:
            _issue(issues, index, resource_type, "resource.status", "status is missing or unsupported.")
        if not _is_object(resource.get("class")):
            _issue(issues, index, resource_type, "resource.class", "class must be a Coding object.")
    if resource_type == "Patient" and resource.get("gender") is not None and resource.get("gender") not in {"male", "female", "other", "unknown"}:
        _issue(issues, index, resource_type, "resource.gender", "gender is unsupported.")


def validate_bundle(bundle: Any) -> list[dict[str, Any]]:
    issues: list[dict[str, str]] = []
    if not _is_object(bundle) or bundle.get("resourceType") != "Bundle":
        raise FHIRValidationError([{"resource_type": "Bundle", "path": "resourceType", "message": "Request must be a FHIR Bundle."}])
    entries = bundle.get("entry")
    if not isinstance(entries, list):
        raise FHIRValidationError([{"resource_type": "Bundle", "path": "entry", "message": "entry must be an array."}])
    for index, entry in enumerate(entries):
        if not _is_object(entry):
            _issue(issues, index, "Bundle", f"entry[{index}]", "Bundle entry must be an object.")
            continue
        _validate_resource(entry.get("resource"), index, issues)
    if issues:
        raise FHIRValidationError(issues)
    patients = [entry["resource"] for entry in entries if entry["resource"]["resourceType"] == "Patient"]
    if len(patients) > 1:
        raise FHIRValidationError([{"resource_type": "Patient", "path": "entry", "message": "A patient-scoped Bundle may contain at most one Patient."}])
    if patients:
        patient_id = patients[0]["id"]
        mismatches = []
        for index, entry in enumerate(entries):
            resource = entry["resource"]
            kind = resource["resourceType"]
            subject = resource.get("patient") if kind == "AllergyIntolerance" else resource.get("subject")
            reference = subject.get("reference") if _is_object(subject) else None
            if reference and reference != f"Patient/{patient_id}":
                _issue(mismatches, index, kind, "resource.patient.reference" if kind == "AllergyIntolerance" else "resource.subject.reference", "Resource patient does not match the Bundle Patient.")
        if mismatches:
            raise FHIRValidationError(mismatches)
    return entries


def _medication_concept(resource: dict[str, Any], medications: dict[str, dict[str, Any]]) -> dict[str, Any]:
    concept = resource.get("medicationCodeableConcept")
    if _is_object(concept):
        return {"display": _coded_display(concept), "coding": concept.get("coding", [])}
    reference = resource.get("medicationReference", {}).get("reference")
    if isinstance(reference, str) and reference.startswith("Medication/"):
        linked = medications.get(reference.split("/", 1)[1])
        if linked:
            code = linked.get("code", {})
            return {"display": _coded_display(code), "coding": code.get("coding", []) if _is_object(code) else []}
    return {"display": None, "coding": [], "normalization_status": "NOT_AVAILABLE"}


def _subject_id(resource: dict[str, Any]) -> str | None:
    subject = resource.get("subject")
    reference = subject.get("reference") if _is_object(subject) else None
    if isinstance(reference, str) and reference.startswith("Patient/"):
        return reference.split("/", 1)[1]
    return None


def _normalized_medication(concept: dict[str, Any], normalizer) -> dict[str, Any]:
    display = concept.get("display")
    if not display:
        return {**concept, "normalized_name": None, "normalization_status": "NOT_AVAILABLE"}
    result = normalizer(display)
    canonical = result.get("canonical_entity")
    return {
        **concept,
        "source_display": display,
        "normalized_name": canonical.get("name") if canonical else None,
        "normalization_status": result.get("status", "NOT_AVAILABLE"),
        "normalization_provider": result.get("provider"),
    }


def normalize_bundle(bundle: Any, normalizer, *, now: datetime | None = None, max_age_hours: int = 24) -> dict[str, Any]:
    """Validate then map only known fields to an internal, explicitly partial model."""
    entries = validate_bundle(bundle)
    resources = [entry["resource"] for entry in entries]
    medication_resources = {resource["id"]: resource for resource in resources if resource["resourceType"] == "Medication"}
    result: dict[str, Any] = {
        "adapter_version": FHIR_ADAPTER_VERSION,
        "patient": None,
        "allergies": [],
        "conditions": [],
        "medications": [],
        "medication_requests": [],
        "medication_statements": [],
        "observations": [],
        "encounters": [],
        "data_quality": {},
    }
    if bundle_patient := next((resource for resource in resources if resource["resourceType"] == "Patient"), None):
        result["patient"] = {
            "id": bundle_patient["id"],
            "gender": bundle_patient.get("gender"),
            "birth_date": bundle_patient.get("birthDate"),
            "identifiers_present": bool(bundle_patient.get("identifier")),
        }
    for resource in resources:
        resource_type = resource["resourceType"]
        rid = resource["id"]
        if resource_type == "Medication":
            result["medications"].append({"id": rid, "concept": _normalized_medication({"display": _coded_display(resource.get("code")), "coding": resource.get("code", {}).get("coding", [])}, normalizer)})
        elif resource_type == "AllergyIntolerance":
            result["allergies"].append({"id": rid, "substance": _coded_display(resource.get("code")), "clinical_status": _coded_display(resource.get("clinicalStatus")), "verification_status": _coded_display(resource.get("verificationStatus")), "patient_id": _subject_id(resource)})
        elif resource_type == "Condition":
            result["conditions"].append({"id": rid, "code": _coded_display(resource.get("code")), "clinical_status": _coded_display(resource.get("clinicalStatus")), "verification_status": _coded_display(resource.get("verificationStatus")), "patient_id": _subject_id(resource)})
        elif resource_type in {"MedicationRequest", "MedicationStatement"}:
            concept = _normalized_medication(_medication_concept(resource, medication_resources), normalizer)
            dose = None
            unit = None
            frequency = None
            instructions = resource.get("dosageInstruction")
            if isinstance(instructions, list) and instructions and _is_object(instructions[0]):
                dosage = instructions[0]
                rates = dosage.get("doseAndRate", [])
                quantity = rates[0].get("doseQuantity") if rates else None
                if _is_object(quantity):
                    dose = quantity.get("value")
                    unit = quantity.get("unit")
                frequency = dosage.get("text")
            target = "medication_requests" if resource_type == "MedicationRequest" else "medication_statements"
            result[target].append({"id": rid, "status": resource.get("status"), "intent": resource.get("intent"), "medication": concept, "patient_id": _subject_id(resource), "dose": dose, "unit": unit, "frequency": frequency, "authored_at": resource.get("authoredOn")})
        elif resource_type == "Observation":
            value_keys = ("valueQuantity", "valueString", "valueInteger", "valueBoolean", "valueCodeableConcept", "valueDateTime", "valueRange")
            value = next(({key: resource[key]} for key in value_keys if key in resource), None)
            result["observations"].append({"id": rid, "code": _coded_display(resource.get("code")), "status": resource.get("status"), "value": value, "value_status": "KNOWN" if value is not None else "NOT_AVAILABLE", "effective": resource.get("effectiveDateTime") or resource.get("effectivePeriod"), "patient_id": _subject_id(resource)})
        elif resource_type == "Encounter":
            result["encounters"].append({"id": rid, "status": resource.get("status"), "class": resource.get("class"), "type": resource.get("type"), "period": resource.get("period"), "patient_id": _subject_id(resource)})

    last_updated = []
    for resource in resources:
        meta = resource.get("meta")
        value = meta.get("lastUpdated") if _is_object(meta) else None
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                last_updated.append(parsed)
            except ValueError:
                continue
    current = now or datetime.now(timezone.utc)
    newest = max(last_updated) if last_updated else None
    if not resources:
        freshness = "UNAVAILABLE"
    elif newest is None:
        freshness = "UNKNOWN"
    elif (current - newest).total_seconds() > max_age_hours * 3600:
        freshness = "STALE"
    else:
        freshness = "CURRENT"
    result["data_quality"] = {
        "fhir_context": {"status": "AVAILABLE" if resources else "UNAVAILABLE", "freshness": freshness, "last_updated": newest.isoformat() if newest else None},
        "adapter_version": FHIR_ADAPTER_VERSION,
        "resource_counts": {key: len(result[key]) for key in ("allergies", "conditions", "medications", "medication_requests", "medication_statements", "observations", "encounters")},
        "medication_normalization": "UNKNOWN" if any(item["medication"].get("normalization_status") != "NORMALIZED" for key in ("medication_requests", "medication_statements") for item in result[key]) else "NORMALIZED",
    }
    return result
