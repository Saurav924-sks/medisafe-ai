"""Security and regression checks using synthetic identities and records only."""

from app.core import security
from app.models.clinical import Organization, Role, User, UserRole
from app.models import models as legacy_models
from app.models.models import Patient


API_KEY = "synthetic-test-api-key"


def _headers(clinician_id=None, api_key=API_KEY):
    result = {"X-API-Key": api_key}
    if clinician_id is not None:
        result["X-Clinician-ID"] = str(clinician_id)
    return result


def _user(db_session, role_name, organization_id=1):
    role = db_session.query(Role).filter_by(name=role_name).first()
    if role is None:
        role = Role(name=role_name)
        db_session.add(role)
        db_session.flush()
    user = User(
        organization_id=organization_id,
        email=f"synthetic-{role_name.lower()}-{organization_id}@tests.invalid",
        email_normalized=f"synthetic-{role_name.lower()}-{organization_id}@tests.invalid",
        display_name=f"Synthetic {role_name}",
    )
    db_session.add(user)
    db_session.flush()
    db_session.add(UserRole(user_id=user.id, role_id=role.id))
    db_session.commit()
    return user


def test_missing_and_invalid_credentials_are_rejected(client, db_session):
    doctor = _user(db_session, "DOCTOR")
    assert client.get("/api/v1/auth/session").status_code == 401
    assert client.get("/api/v1/auth/session", headers=_headers(doctor.id, "wrong" )).status_code == 401
    assert client.get("/api/v1/auth/session", headers=_headers(999999)).status_code == 401


def test_unconfigured_credential_fails_closed(client, db_session, monkeypatch):
    doctor = _user(db_session, "DOCTOR")
    monkeypatch.setattr(security, "CONFIGURED_API_KEY", "")
    response = client.get("/api/v1/auth/session", headers=_headers(doctor.id))
    assert response.status_code == 503


def test_read_only_role_cannot_write_and_unknown_role_cannot_authenticate(client, db_session):
    readonly = _user(db_session, "READ_ONLY")
    patient = {"name": "Synthetic Security Patient", "age": 45, "gender": "unknown"}
    assert client.post("/api/v1/patients", json=patient, headers=_headers(readonly.id)).status_code == 403
    unknown_role = _user(db_session, "UNASSIGNED")
    assert client.get("/api/v1/auth/session", headers=_headers(unknown_role.id)).status_code == 403


def test_patient_access_is_organization_scoped(client, db_session):
    foreign_org = Organization(name="Synthetic Other Organization")
    db_session.add(foreign_org)
    db_session.flush()
    doctor = _user(db_session, "DOCTOR", organization_id=foreign_org.id)
    patient = Patient(name="Synthetic Foreign Patient", age=50, gender="unknown", organization_id=1)
    db_session.add(patient)
    db_session.commit()
    response = client.get(f"/api/v1/patients/{patient.id}", headers=_headers(doctor.id))
    assert response.status_code == 404


def test_patient_query_payload_is_data_not_sql(client, db_session):
    doctor = _user(db_session, "DOCTOR")
    payload = {"name": "Synthetic ' OR 1=1 -- Patient", "age": 37, "gender": "unknown"}
    created = client.post("/api/v1/patients", json=payload, headers=_headers(doctor.id))
    assert created.status_code == 200, created.text
    assert created.json()["name"] == payload["name"]
    rows = client.get("/api/v1/patients", headers=_headers(doctor.id)).json()
    assert len(rows) == 1
    assert rows[0]["id"] == created.json()["id"]


def test_malformed_and_oversized_patient_payloads_fail_validation(client, db_session):
    doctor = _user(db_session, "DOCTOR")
    headers = _headers(doctor.id)
    assert client.post("/api/v1/patients", json={"name": "", "age": -1, "gender": "unknown"}, headers=headers).status_code == 422
    assert client.post("/api/v1/patients", json={"name": "x" * 101, "age": 24, "gender": "unknown"}, headers=headers).status_code == 422
    assert client.post("/api/v1/patients", data="{malformed", headers={**headers, "Content-Type": "application/json"}).status_code == 422


def test_prescription_payload_rejects_invalid_route_and_unknown_fields(client, db_session):
    doctor = _user(db_session, "DOCTOR")
    patient_response = client.post(
        "/api/v1/patients",
        json={"name": "Synthetic Prescription Patient", "age": 52, "gender": "unknown"},
        headers=_headers(doctor.id),
    )
    assert patient_response.status_code == 200
    response = client.post(
        "/api/v1/prescriptions",
        json={"patient_id": patient_response.json()["id"], "medication_orders": [{
            "medication_name": "SyntheticUnknownMedication",
            "dose": 20,
            "unit": "mg",
            "route": "teleport",
            "frequency": "once daily",
        }]},
        headers=_headers(doctor.id),
    )
    assert response.status_code == 422


def test_unrecognized_medication_cannot_be_confirmed_or_analyzed(client, db_session):
    doctor = _user(db_session, "DOCTOR")
    patient = client.post(
        "/api/v1/patients",
        json={"name": "Synthetic Unknown Medication Patient", "age": 61, "gender": "unknown"},
        headers=_headers(doctor.id),
    ).json()
    prescription = client.post(
        "/api/v1/prescriptions",
        json={"patient_id": patient["id"], "medication_orders": [{
            "medication_name": "UncataloguedSyntheticDrug", "dose": 10,
            "unit": "mg", "route": "oral", "frequency": "once daily",
        }]},
        headers=_headers(doctor.id),
    )
    assert prescription.status_code == 200
    order = prescription.json()["orders"][0]
    assert order["normalization_status"] != "NORMALIZED"
    confirmation = client.post(
        f"/api/v1/prescriptions/{prescription.json()['id']}/confirm-normalization",
        json={"order_id": order["id"], "confirmed": True},
        headers=_headers(doctor.id),
    )
    assert confirmation.status_code == 409


def test_legacy_analysis_feedback_and_reanalysis_routes_require_clinician(client, db_session):
    paths = (
        ("GET", "/api/v1/prescriptions/analyze/1", None),
        ("POST", "/api/v1/prescriptions/analyze/1/feedback", {"alert_index": 0}),
        ("POST", "/api/v1/prescriptions/analyze/1/reevaluate", None),
    )
    for method, path, payload in paths:
        response = client.request(method, path, json=payload)
        assert response.status_code == 401

    readonly = _user(db_session, "READ_ONLY")
    response = client.post(
        "/api/v1/prescriptions/analyze/1/reevaluate",
        headers=_headers(readonly.id),
    )
    assert response.status_code == 403


def test_legacy_analysis_history_is_tenant_scoped(client, db_session):
    other_org = Organization(name="Synthetic History Organization")
    db_session.add(other_org)
    db_session.flush()
    doctor = _user(db_session, "DOCTOR")
    foreign_patient = Patient(
        name="Synthetic Foreign History Patient",
        age=44,
        gender="unknown",
        organization_id=other_org.id,
    )
    db_session.add(foreign_patient)
    db_session.flush()
    prescription = legacy_models.Prescription(
        patient_id=foreign_patient.id,
        organization_id=other_org.id,
        status="DRAFT",
        parser_status="SYNTHETIC_TEST",
    )
    db_session.add(prescription)
    db_session.commit()
    response = client.get(
        f"/api/v1/prescriptions/analyze/{prescription.id}",
        headers=_headers(doctor.id),
    )
    assert response.status_code == 404
