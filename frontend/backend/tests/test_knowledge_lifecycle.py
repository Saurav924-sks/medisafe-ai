import json
from datetime import date
from pathlib import Path

from app.models.clinical import AuditEvent, KnowledgeStatus, KnowledgeVersion, Role, User, UserRole, Analysis
from app.models.models import Patient

API_KEY_HEADERS = {"X-API-Key": "synthetic-test-api-key", "X-Clinician-ID": "2"}
ARTIFACT_PATH = Path(__file__).resolve().parents[2] / "knowledge_base" / "versions" / "v1.json"


def _clinician(db_session, role_name):
    role = db_session.query(Role).filter_by(name=role_name).first()
    if role is None:
        role = Role(name=role_name)
        db_session.add(role)
        db_session.flush()
    user = User(
        organization_id=1,
        email=f"{role_name.lower()}-knowledge@test.invalid",
        email_normalized=f"{role_name.lower()}-knowledge@test.invalid",
        display_name=f"Synthetic {role_name} Reviewer",
    )
    db_session.add(user)
    db_session.flush()
    db_session.add(UserRole(user_id=user.id, role_id=role.id))
    db_session.commit()
    return user


def _headers(user):
    return {**API_KEY_HEADERS, "X-Clinician-ID": str(user.id)}


def _candidate_file(version="2"):
    artifact = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8-sig"))
    artifact["manifest"]["dataset"] = "medisafe-clinical"
    artifact["manifest"]["version"] = version
    artifact["manifest"]["last_reviewed"] = None
    artifact["manifest"]["review_status"] = "NOT_REVIEWED"
    artifact["manifest"]["review_note"] = "prototype data — not clinically reviewed"
    return json.dumps(artifact, ensure_ascii=False).encode("utf-8")


def _active_fixture(db_session):
    return db_session.query(KnowledgeVersion).filter_by(dataset="medisafe-clinical", lifecycle_stage="ACTIVE").one()


def test_import_validation_failure_does_not_create_version_or_audit(client, db_session):
    reviewer = _clinician(db_session, "CLINICAL_REVIEWER")
    artifact = json.loads(_candidate_file())
    artifact["data"]["drug_drug_interactions"][0]["severity"] = "IMPOSSIBLE"

    response = client.post(
        "/api/v1/knowledge/import",
        content=json.dumps(artifact).encode("utf-8"),
        headers={**_headers(reviewer), "Content-Type": "application/json"},
    )

    assert response.status_code == 422
    assert db_session.query(KnowledgeVersion).filter_by(dataset="medisafe-clinical", version="2").count() == 0
    assert db_session.query(AuditEvent).filter(AuditEvent.action.like("KNOWLEDGE_%")).count() == 0


def test_reviewer_activation_requires_review_and_supports_audited_rollback(client, db_session):
    reviewer = _clinician(db_session, "CLINICAL_REVIEWER")
    doctor = _clinician(db_session, "DOCTOR")
    active_before = _active_fixture(db_session)
    imported = client.post(
        "/api/v1/knowledge/import",
        content=_candidate_file(),
        headers={**_headers(reviewer), "Content-Type": "application/json"},
    )
    assert imported.status_code == 200, imported.text
    version_id = imported.json()["id"]
    assert imported.json()["lifecycle_stage"] == "REVIEW_PENDING"

    denied_review = client.post(
        f"/api/v1/knowledge/{version_id}/review",
        json={"review_note": "Reviewed synthetic test knowledge data"},
        headers=_headers(doctor),
    )
    assert denied_review.status_code == 403
    unreviewed_activation = client.post(
        f"/api/v1/knowledge/{version_id}/activate",
        json={"expected_active_version_id": active_before.id},
        headers=_headers(reviewer),
    )
    assert unreviewed_activation.status_code == 409
    assert _active_fixture(db_session).id == active_before.id

    reviewed = client.post(
        f"/api/v1/knowledge/{version_id}/review",
        json={"review_note": "Reviewed synthetic test knowledge data"},
        headers=_headers(reviewer),
    )
    assert reviewed.status_code == 200, reviewed.text
    activated = client.post(
        f"/api/v1/knowledge/{version_id}/activate",
        json={"expected_active_version_id": active_before.id},
        headers=_headers(reviewer),
    )
    assert activated.status_code == 200, activated.text
    assert activated.json()["previous_active_version_id"] == active_before.id
    db_session.refresh(active_before)
    assert active_before.lifecycle_stage == "SUPERSEDED"
    active_after = _active_fixture(db_session)
    assert active_after.id == version_id

    rollback = client.post(
        f"/api/v1/knowledge/{active_before.id}/rollback",
        json={"expected_active_version_id": active_after.id},
        headers=_headers(reviewer),
    )
    assert rollback.status_code == 200, rollback.text
    assert rollback.json()["id"] == active_before.id
    assert _active_fixture(db_session).id == active_before.id
    assert db_session.query(AuditEvent).filter_by(action="KNOWLEDGE_ACTIVATED").one().details["previous_active_version_id"] == active_before.id
    assert db_session.query(AuditEvent).filter_by(action="KNOWLEDGE_ROLLED_BACK").one().details["previous_active_version_id"] == active_after.id


def test_analysis_records_the_active_knowledge_version(client, db_session):
    patient = Patient(name="Synthetic Test Patient", age=42, gender="unknown")
    db_session.add(patient)
    db_session.commit()
    active = _active_fixture(db_session)

    response = client.post(
        "/api/v1/prescriptions/analyze",
        json={"patient_id": patient.id, "raw_text": "Take paracetamol 500mg twice daily for 3 days.", "items": []},
        headers=API_KEY_HEADERS,
    )

    assert response.status_code == 200, response.text
    analysis = db_session.query(Analysis).filter_by(id=response.json()["normalized_analysis_id"]).one()
    assert analysis.knowledge_version_id == active.id
    assert analysis.rule_set_version == f"{active.dataset}:{active.version}"
    assert response.json()["knowledge_version"] == active.version
    assert analysis.status.value == "PARTIALLY_EVALUATED"
    assert response.json()["safety_domains"]["renal"] is False


def test_analysis_fails_incomplete_when_only_unreviewed_knowledge_is_available(client, db_session):
    active = _active_fixture(db_session)
    active.lifecycle_stage = "REVIEW_PENDING"
    active.reviewed_by = None
    active.last_reviewed = None
    db_session.commit()
    patient = Patient(name="Synthetic Test Patient", age=42, gender="unknown")
    db_session.add(patient)
    db_session.commit()

    response = client.post(
        "/api/v1/prescriptions/analyze",
        json={"patient_id": patient.id, "raw_text": "Take paracetamol 500mg daily.", "items": []},
        headers=API_KEY_HEADERS,
    )

    assert response.status_code == 503
    assert "No clinically reviewed knowledge version is active" in response.json()["detail"]


