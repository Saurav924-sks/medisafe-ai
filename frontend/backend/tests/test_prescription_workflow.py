import json

import pytest

from app.models.clinical import Alert, Analysis, AuditEvent
from app.schemas.schemas import PrescriptionCreateRequest
from app.services.nlp_parser import parse_prescription_draft
from app.services.terminology import (
    NORMALIZATION_REVIEW_MESSAGE,
    ExternalTerminologyProvider,
    LocalTerminologyProvider,
    MedicationTerminologyService,
)

API_KEY_HEADERS = {"X-API-Key": "synthetic-test-api-key", "X-Clinician-ID": "2"}


def _create_patient(client):
    response = client.post(
        "/api/v1/patients",
        json={"name": "Synthetic Test Patient", "age": 42, "gender": "unknown"},
        headers=API_KEY_HEADERS,
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _manual_order(name="Amoxicillin"):
    return {
        "medication_name": name,
        "dose": "250",
        "unit": "mg",
        "route": "oral",
        "frequency": "twice daily",
        "duration": "7 days",
        "indication": "Synthetic test indication",
    }


def test_local_terminology_exact_match_does_not_invent_identifiers():
    result = LocalTerminologyProvider().normalize(" amoxicillin ")

    assert result.status == "NORMALIZED"
    assert result.confidence == 1.0
    assert result.match_method == "EXACT_NAME"
    assert result.canonical_entity["name"] == "Amoxicillin"
    assert result.canonical_entity["concept_id"] is None
    assert result.canonical_entity["strength"]["value"] is None
    assert result.canonical_entity["dose_form"] is None
    assert result.canonical_entity["route"] is None


def test_local_terminology_ambiguous_ingredient_requires_review(tmp_path):
    dataset = tmp_path / "terminology.json"
    dataset.write_text(json.dumps({
        "drugs": {
            "Synthetic Product A": {"active_ingredient": "Synthetic Shared Ingredient"},
            "Synthetic Product B": {"active_ingredient": "Synthetic Shared Ingredient"},
        }
    }), encoding="utf-8")

    result = LocalTerminologyProvider(dataset).normalize("Synthetic Shared Ingredient")

    assert result.status == "AMBIGUOUS"
    assert result.canonical_entity is None
    assert result.match_method == "EXACT_INGREDIENT"
    assert len(result.candidates) == 2
    assert result.message == NORMALIZATION_REVIEW_MESSAGE


def test_unknown_and_below_threshold_terms_require_review():
    provider = LocalTerminologyProvider()

    unknown = provider.normalize("Synthetic Unknown Medication")
    typo = provider.normalize("Ibuprofn")

    assert unknown.status == "REVIEW_REQUIRED"
    assert unknown.canonical_entity is None
    assert unknown.message == NORMALIZATION_REVIEW_MESSAGE
    assert typo.status == "REVIEW_REQUIRED"
    assert typo.match_method == "BELOW_CONFIDENCE_THRESHOLD"


def test_external_terminology_stub_never_returns_an_invented_concept():
    result = ExternalTerminologyProvider("test-jurisdiction").normalize("Synthetic medication")

    assert result.status == "NOT_AVAILABLE"
    assert result.canonical_entity is None
    assert result.confidence is None
    assert result.message == NORMALIZATION_REVIEW_MESSAGE


def test_missing_local_reference_reports_not_available(tmp_path):
    service = MedicationTerminologyService(
        local_provider=LocalTerminologyProvider(tmp_path / "missing.json"),
    )

    result = service.normalize("Amoxicillin")

    assert result.status == "NOT_AVAILABLE"
    assert result.canonical_entity is None
    assert result.message == NORMALIZATION_REVIEW_MESSAGE


def test_natural_language_parser_produces_draft_or_manual_entry():
    draft = parse_prescription_draft("Take amoxicillin 500 mg twice daily for 7 days")
    failure = parse_prescription_draft("Take a new unknown medication")

    assert draft["status"] == "DRAFT_REVIEW_REQUIRED"
    assert draft["orders"] == [{
        "medication_name": "amoxicillin",
        "dose": "500",
        "unit": "MG",
        "route": None,
        "frequency": "Twice daily",
        "duration": "7 days",
        "indication": None,
    }]
    assert failure == {"status": "MANUAL_ENTRY_REQUIRED", "orders": []}


def test_structured_order_validation_rejects_invalid_dose_route_and_frequency():
    base = {
        "patient_id": 1,
        "medication_orders": [_manual_order()],
    }
    assert PrescriptionCreateRequest.model_validate(base)

    invalid_dose = {**base, "medication_orders": [{**_manual_order(), "dose": "0"}]}
    invalid_route = {**base, "medication_orders": [{**_manual_order(), "route": "teleportation"}]}
    invalid_frequency = {**base, "medication_orders": [{**_manual_order(), "frequency": "whenever"}]}
    for invalid in (invalid_dose, invalid_route, invalid_frequency):
        with pytest.raises(ValueError):
            PrescriptionCreateRequest.model_validate(invalid)


@pytest.mark.parametrize("order", [
    {**_manual_order(), "dose": "0"},
    {**_manual_order(), "route": "teleportation"},
    {**_manual_order(), "frequency": "whenever"},
])
def test_api_rejects_invalid_structured_orders(client, order):
    patient_id = _create_patient(client)
    response = client.post(
        "/api/v1/prescriptions",
        json={"patient_id": patient_id, "medication_orders": [order]},
        headers=API_KEY_HEADERS,
    )
    assert response.status_code == 422


def test_api_creates_draft_gets_it_and_records_minimized_audit_events(client, db_session):
    patient_id = _create_patient(client)
    response = client.post(
        "/api/v1/prescriptions",
        json={"patient_id": patient_id, "medication_orders": [_manual_order()]},
        headers=API_KEY_HEADERS,
    )

    assert response.status_code == 200, response.text
    created = response.json()
    assert created["status"] == "DRAFT"
    assert created["parser_status"] == "STRUCTURED_DRAFT"
    assert created["clinician_review_required"] is True
    assert created["orders"][0]["status"] == "DRAFT"
    assert created["orders"][0]["route"] == "oral"
    assert created["orders"][0]["normalization_status"] == "NORMALIZED"
    assert created["orders"][0]["canonical_entity"]["concept_id"] is None

    read = client.get(f"/api/v1/prescriptions/{created['id']}", headers=API_KEY_HEADERS)
    assert read.status_code == 200, read.text
    assert read.json()["orders"][0]["indication"] == "Synthetic test indication"
    assert read.json()["orders"][0]["clinician_review_required"] is True

    events = db_session.query(AuditEvent).filter(
        AuditEvent.entity_id.in_([str(created["id"]), str(created["orders"][0]["id"])])
    ).all()
    assert {event.action for event in events} == {
        "PRESCRIPTION_CREATED", "MEDICATION_NORMALIZATION_OUTCOME",
    }
    event_details = [event.details for event in events]
    assert all("Amoxicillin" not in json.dumps(details) for details in event_details)
    assert all("Synthetic test indication" not in json.dumps(details) for details in event_details)


def test_parser_endpoint_keeps_orders_as_drafts_and_requires_manual_entry_on_failure(client):
    patient_id = _create_patient(client)
    parsed = client.post(
        "/api/v1/prescriptions",
        json={"patient_id": patient_id, "raw_text": "Take amoxicillin 500 mg twice daily for 7 days"},
        headers=API_KEY_HEADERS,
    )
    failed = client.post(
        "/api/v1/prescriptions",
        json={"patient_id": patient_id, "raw_text": "Take a new unknown medication"},
        headers=API_KEY_HEADERS,
    )

    assert parsed.status_code == 200, parsed.text
    assert parsed.json()["parser_status"] == "DRAFT_REVIEW_REQUIRED"
    assert parsed.json()["orders"][0]["status"] == "DRAFT"
    assert parsed.json()["orders"][0]["route"] is None
    assert parsed.json()["clinician_review_required"] is True
    assert failed.status_code == 200, failed.text
    assert failed.json()["parser_status"] == "MANUAL_ENTRY_REQUIRED"
    assert failed.json()["orders"] == []
    assert failed.json()["clinician_review_required"] is True


def test_prescription_endpoints_require_api_key(client):
    create = client.post(
        "/api/v1/prescriptions",
        json={"patient_id": 1, "medication_orders": [_manual_order()]},
    )
    read = client.get("/api/v1/prescriptions/1")

    assert create.status_code == 401
    assert read.status_code == 401


def test_legacy_analyzer_is_draft_only_and_rejects_fuzzy_or_item_only_input(client):
    patient_id = _create_patient(client)
    exact = client.post(
        "/api/v1/prescriptions/analyze",
        json={
            "patient_id": patient_id,
            "raw_text": "Take amoxicillin 500 mg twice daily",
            "items": [],
        },
        headers=API_KEY_HEADERS,
    )
    fuzzy = client.post(
        "/api/v1/prescriptions/analyze",
        json={"patient_id": patient_id, "raw_text": "Take ibuprofn 400 mg daily", "items": []},
        headers=API_KEY_HEADERS,
    )
    item_only = client.post(
        "/api/v1/prescriptions/analyze",
        json={
            "patient_id": patient_id,
            "raw_text": None,
            "items": [{"drug_name": "Amoxicillin", "dose": "500", "unit": "mg"}],
        },
        headers=API_KEY_HEADERS,
    )

    assert exact.status_code == 200, exact.text
    assert exact.json()["prescription_status"] == "DRAFT"
    assert exact.json()["parser_status"] == "DRAFT_REVIEW_REQUIRED"
    assert fuzzy.status_code == 422
    assert item_only.status_code == 409



def test_structured_prescription_requires_normalization_confirmation_before_analysis(client, db_session):
    patient_id = _create_patient(client)
    created = client.post("/api/v1/prescriptions", json={"patient_id": patient_id, "medication_orders": [_manual_order()]}, headers=API_KEY_HEADERS)
    assert created.status_code == 200, created.text
    prescription_id = created.json()["id"]

    rejected = client.post(f"/api/v1/prescriptions/{prescription_id}/analyze", headers=API_KEY_HEADERS)
    assert rejected.status_code == 409

    confirmed = client.post(f"/api/v1/prescriptions/{prescription_id}/confirm-normalization", headers=API_KEY_HEADERS)
    assert confirmed.status_code == 200, confirmed.text
    analyzed = client.post(f"/api/v1/prescriptions/{prescription_id}/analyze", headers=API_KEY_HEADERS)
    assert analyzed.status_code == 200, analyzed.text
    result = analyzed.json()
    assert result["analysis_status"] == "PARTIALLY_EVALUATED"
    assert result["safety_domains"]["renal"] == "NOT_EVALUATED"
    assert result["data_quality"]["allergy_verification"] == "UNKNOWN"
    assert db_session.query(Analysis).filter_by(id=result["id"]).one()
    assert db_session.query(Alert).filter_by(analysis_id=result["id"]).count() == len(result["alerts"])
