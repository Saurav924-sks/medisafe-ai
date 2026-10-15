from app.interop.fhir.adapter import normalize_bundle


def test_fhir_adapter_maps_supported_resource_types_with_synthetic_data():
    bundle = {"resourceType": "Bundle", "entry": [
        {"resource": {"resourceType": "Patient", "id": "synthetic-1", "gender": "unknown"}},
        {"resource": {"resourceType": "AllergyIntolerance", "id": "a1", "patient": {"reference": "Patient/synthetic-1"}, "code": {"text": "synthetic allergen"}}},
        {"resource": {"resourceType": "Condition", "id": "c1", "subject": {"reference": "Patient/synthetic-1"}, "code": {"text": "synthetic condition"}}},
        {"resource": {"resourceType": "Medication", "id": "m1", "code": {"text": "Synthetic Drug"}}},
        {"resource": {"resourceType": "MedicationRequest", "id": "mr1", "status": "active", "intent": "order", "subject": {"reference": "Patient/synthetic-1"}, "medicationCodeableConcept": {"text": "Synthetic Drug"}, "dosageInstruction": [{"text": "1 synthetic unit"}]}},
        {"resource": {"resourceType": "MedicationStatement", "id": "ms1", "status": "active", "subject": {"reference": "Patient/synthetic-1"}, "medicationCodeableConcept": {"text": "Synthetic Drug"}}},
        {"resource": {"resourceType": "Observation", "id": "o1", "subject": {"reference": "Patient/synthetic-1"}, "status": "final", "code": {"text": "synthetic observation"}}},
        {"resource": {"resourceType": "Encounter", "id": "e1", "subject": {"reference": "Patient/synthetic-1"}, "status": "finished", "class": {"code": "AMB"}}},
    ]}
    mapped = normalize_bundle(bundle, lambda name: {"canonical_entity": {"name": name}, "status": "NORMALIZED", "provider": "synthetic-test"})
    assert mapped["patient"]["id"] == "synthetic-1"
    assert len(mapped["allergies"]) == len(mapped["conditions"]) == len(mapped["medications"]) == 1
    assert len(mapped["medication_requests"]) == len(mapped["medication_statements"]) == 1
    assert mapped["observations"][0]["value_status"] == "NOT_AVAILABLE"
    assert len(mapped["encounters"]) == 1
    assert mapped["data_quality"]["fhir_context"]["freshness"] == "UNKNOWN"


def test_malformed_fhir_resource_is_rejected_with_path():
    import pytest
    from app.interop.fhir.adapter import FHIRValidationError
    bundle = {"resourceType": "Bundle", "entry": [{"resource": {"resourceType": "MedicationRequest", "id": "x"}}]}
    with pytest.raises(FHIRValidationError) as error:
        normalize_bundle(bundle, lambda _: {})
    assert any(issue["path"] == "resource.status" for issue in error.value.issues)
    assert any(issue["path"] == "resource.medication[x]" for issue in error.value.issues)


def test_stale_fhir_context_is_explicit():
    from datetime import datetime, timezone
    bundle = {"resourceType": "Bundle", "entry": [{"resource": {"resourceType": "Patient", "id": "synthetic-1", "meta": {"lastUpdated": "2020-01-01T00:00:00Z"}}}]}
    mapped = normalize_bundle(bundle, lambda _: {}, now=datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert mapped["data_quality"]["fhir_context"]["freshness"] == "STALE"


def test_fhir_analysis_uses_submitted_data_and_reports_quality(client):
    bundle = {"resourceType": "Bundle", "entry": [
        {"resource": {"resourceType": "Patient", "id": "synthetic-patient", "meta": {"lastUpdated": "2026-10-01T00:00:00Z"}}},
        {"resource": {"resourceType": "MedicationRequest", "id": "synthetic-order", "status": "active", "intent": "order", "subject": {"reference": "Patient/synthetic-patient"}, "medicationCodeableConcept": {"text": "Synthetic Unlisted Drug"}, "meta": {"lastUpdated": "2026-10-01T00:00:00Z"}}},
    ]}
    response = client.post("/api/v1/fhir/analyze", json=bundle, headers={"X-API-Key": "synthetic-test-api-key", "X-Clinician-ID": "1"})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["analysis_status"] == "INCOMPLETE"
    assert result["fhir_context"]["medication_requests"][0]["medication"]["normalization_status"] != "NORMALIZED"
    assert "data_quality" in result

    status = client.get("/api/v1/system/status").json()
    assert status["services"]["nlp_engine"] in {"available", "unavailable"}

