from datetime import date

import pytest

from app.models.clinical import (
    Alert,
    AlertReviewAction,
    AlertReviewActionType,
    AlertStatus,
    Analysis,
    AuditEvent,
    ClinicalRule,
    ClinicalSeverity,
    Feedback,
    KnowledgeStatus,
    KnowledgeVersion,
    Organization,
    Role,
    RuleStatus,
    User,
    UserRole,
)
from app.models.models import Patient

API_KEY_HEADERS = {"X-API-Key": "synthetic-test-api-key"}


def _create_clinician(db_session, role_name):
    organization = db_session.query(Organization).filter(Organization.id == 1).one()
    role = db_session.query(Role).filter(Role.name == role_name).first()
    if role is None:
        role = Role(name=role_name)
        db_session.add(role)
        db_session.flush()
    clinician = User(
        organization_id=organization.id,
        email=f"{role_name.lower()}@synthetic.example",
        email_normalized=f"{role_name.lower()}@synthetic.example",
        display_name=f"Synthetic {role_name} Clinician",
    )
    db_session.add(clinician)
    db_session.flush()
    db_session.add(UserRole(user_id=clinician.id, role_id=role.id))
    db_session.commit()
    return clinician


def _create_versioned_alert(db_session, severity=ClinicalSeverity.CRITICAL):
    patient = Patient(name="Synthetic Test Patient", age=42, gender="unknown")
    db_session.add(patient)
    db_session.flush()
    knowledge = KnowledgeVersion(
        dataset="synthetic-review-tests",
        version="kb-test-v1",
        source="Synthetic test fixture",
        source_version="1",
        effective_date=date(2026, 1, 1),
        status=KnowledgeStatus.LOADED,
    )
    db_session.add(knowledge)
    db_session.flush()
    analysis = Analysis(
        organization_id=1,
        patient_id=patient.id,
        knowledge_version_id=knowledge.id,
        rule_set_version="rules-test-v2",
    )
    db_session.add(analysis)
    db_session.flush()
    rule = ClinicalRule(
        rule_id="SYNTHETIC-TEST-RULE",
        version="rule-test-v3",
        source="Synthetic test fixture",
        source_version="1",
        effective_date=date(2026, 1, 1),
        evidence_reference="Synthetic test evidence",
        domain="drug_drug",
        severity=severity,
        trigger_conditions={"synthetic": True},
        rationale="Synthetic test rationale",
        recommendation="Synthetic test recommendation",
        status=RuleStatus.ACTIVE,
        knowledge_version_id=knowledge.id,
    )
    db_session.add(rule)
    db_session.flush()
    alert = Alert(
        organization_id=1,
        analysis_id=analysis.id,
        clinical_rule_id=rule.id,
        alert_index=0,
        domain="drug_drug",
        severity=severity,
        status=AlertStatus.OPEN,
        message="Synthetic test alert",
        details={"type": "Synthetic Interaction"},
    )
    db_session.add(alert)
    db_session.commit()
    return analysis, rule, alert


def _headers(clinician_id):
    return {**API_KEY_HEADERS, "X-Clinician-ID": str(clinician_id)}


def test_role_permissions_restrict_read_only_and_pharmacist_override(client, db_session):
    pharmacist = _create_clinician(db_session, "PHARMACIST")
    readonly = _create_clinician(db_session, "READ_ONLY")
    _, _, alert = _create_versioned_alert(db_session)
    payload = {"action": "OVERRIDE", "override_reason": "CLINICAL_JUDGMENT"}

    pharmacist_response = client.post(
        f"/api/v1/alerts/{alert.id}/actions", json=payload,
        headers=_headers(pharmacist.id),
    )
    readonly_response = client.post(
        f"/api/v1/alerts/{alert.id}/actions", json={"action": "REVIEW"},
        headers=_headers(readonly.id),
    )
    no_identity_response = client.post(
        f"/api/v1/alerts/{alert.id}/actions", json={"action": "REVIEW"},
        headers=API_KEY_HEADERS,
    )

    assert pharmacist_response.status_code == 403
    assert readonly_response.status_code == 403
    assert no_identity_response.status_code == 401
    assert db_session.query(AlertReviewAction).count() == 0


def test_high_severity_override_requires_reason_and_records_immutable_action_audit(client, db_session):
    doctor = _create_clinician(db_session, "DOCTOR")
    _, rule, alert = _create_versioned_alert(db_session)
    original = (alert.status, alert.acknowledged_by, alert.override_reason, alert.message)

    missing_reason = client.post(
        f"/api/v1/alerts/{alert.id}/actions",
        json={"action": "OVERRIDE"},
        headers=_headers(doctor.id),
    )
    assert missing_reason.status_code == 422

    for action in ("REVIEW", "ACKNOWLEDGE", "OVERRIDE", "RESOLVE", "DISMISS"):
        payload = {"action": action, "note": "Synthetic review note"}
        if action == "OVERRIDE":
            payload["override_reason"] = "PATIENT_CONTEXT_NOT_CAPTURED"
            payload["override_reason_text"] = "Synthetic context was not captured"
        response = client.post(
            f"/api/v1/alerts/{alert.id}/actions",
            json=payload,
            headers=_headers(doctor.id),
        )
        assert response.status_code == 200, response.text
        assert response.json()["rule_version"] == rule.version
        assert response.json()["knowledge_base_version"] == "kb-test-v1"

    db_session.refresh(alert)
    assert (alert.status, alert.acknowledged_by, alert.override_reason, alert.message) == original
    actions = db_session.query(AlertReviewAction).filter_by(alert_id=alert.id).all()
    assert len(actions) == 5
    assert all(action.rule_version == rule.version for action in actions)
    audit_rows = db_session.query(AuditEvent).filter(
        AuditEvent.entity_type == "Alert",
        AuditEvent.entity_id == str(alert.id),
    ).all()
    assert len(audit_rows) == 5
    assert all(row.details["rule_version"] == rule.version for row in audit_rows)


def test_override_reason_for_moderate_alert_is_optional(client, db_session):
    doctor = _create_clinician(db_session, "DOCTOR")
    _, _, alert = _create_versioned_alert(db_session, ClinicalSeverity.MODERATE)

    response = client.post(
        f"/api/v1/alerts/{alert.id}/actions",
        json={"action": "OVERRIDE"},
        headers=_headers(doctor.id),
    )

    assert response.status_code == 200, response.text
    assert response.json()["override_reason"] is None


def test_actions_and_feedback_use_analysis_rule_version_when_alert_has_no_rule(client, db_session):
    doctor = _create_clinician(db_session, "DOCTOR")
    analysis, _, alert = _create_versioned_alert(db_session)
    alert.clinical_rule_id = None
    db_session.commit()

    action = client.post(
        f"/api/v1/alerts/{alert.id}/actions",
        json={"action": "REVIEW"},
        headers=_headers(doctor.id),
    )
    feedback = client.post(
        f"/api/v1/alerts/{alert.id}/feedback",
        json={"analysis_id": analysis.id, "feedback": "AGREE"},
        headers=_headers(doctor.id),
    )

    assert action.status_code == 200, action.text
    assert feedback.status_code == 200, feedback.text
    assert action.json()["rule_version"] == analysis.rule_set_version
    assert feedback.json()["rule_version"] == analysis.rule_set_version
    audit_rows = db_session.query(AuditEvent).filter(
        AuditEvent.entity_id == str(alert.id),
    ).all()
    assert len(audit_rows) == 2
    assert all(row.details["rule_version"] == analysis.rule_set_version for row in audit_rows)


def test_feedback_is_versioned_audited_and_isolated_from_alert_and_rule(client, db_session):
    doctor = _create_clinician(db_session, "DOCTOR")
    analysis, rule, alert = _create_versioned_alert(db_session)
    original_rule = (rule.version, rule.severity, rule.status, rule.recommendation)
    original_alert = (alert.status, alert.severity, alert.message, alert.override_reason)

    response = client.post(
        f"/api/v1/alerts/{alert.id}/feedback",
        json={
            "analysis_id": analysis.id,
            "feedback": "DISAGREE",
            "rationale": "Synthetic test rationale",
        },
        headers=_headers(doctor.id),
    )

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["alert_type"] == "Synthetic Interaction"
    assert result["clinician_id"] == doctor.id
    assert result["rule_version"] == rule.version
    assert result["knowledge_base_version"] == "kb-test-v1"

    feedback = db_session.query(Feedback).filter_by(id=result["id"]).one()
    assert feedback.analysis_id == analysis.id
    assert feedback.alert_id == alert.id
    assert feedback.feedback.value == "DISAGREE"
    assert feedback.rationale == "Synthetic test rationale"

    db_session.refresh(rule)
    db_session.refresh(alert)
    assert (rule.version, rule.severity, rule.status, rule.recommendation) == original_rule
    assert (alert.status, alert.severity, alert.message, alert.override_reason) == original_alert
    audit = db_session.query(AuditEvent).filter_by(action="ALERT_FEEDBACK_RECORDED").one()
    assert audit.actor_id == doctor.id
    assert audit.details["rule_version"] == rule.version
    analytics = client.get("/api/v1/feedback/analytics", headers=_headers(doctor.id))
    assert analytics.status_code == 200, analytics.text
    quality = analytics.json()["rule_quality_monitoring"]
    assert quality["changes_rules"] is False
    assert quality["by_rule_version"][rule.version]["DISAGREE"] == 1


def test_review_queue_includes_open_alerts_and_removes_resolved_alerts(client, db_session):
    doctor = _create_clinician(db_session, "DOCTOR")
    _, _, alert = _create_versioned_alert(db_session)

    before = client.get("/api/v1/alerts/review-queue", headers=_headers(doctor.id))
    resolve = client.post(
        f"/api/v1/alerts/{alert.id}/actions",
        json={"action": "RESOLVE"},
        headers=_headers(doctor.id),
    )
    after = client.get("/api/v1/alerts/review-queue", headers=_headers(doctor.id))

    assert before.status_code == 200
    assert any(row["alert_id"] == alert.id for row in before.json())
    assert resolve.status_code == 200, resolve.text
    assert after.status_code == 200
    assert all(row["alert_id"] != alert.id for row in after.json())


def test_review_queue_includes_latest_acknowledgement_without_mutating_alert(client, db_session):
    doctor = _create_clinician(db_session, "DOCTOR")
    _, _, alert = _create_versioned_alert(db_session)
    original_status = alert.status

    response = client.post(
        f"/api/v1/alerts/{alert.id}/actions",
        json={"action": "ACKNOWLEDGE"},
        headers=_headers(doctor.id),
    )
    queue = client.get("/api/v1/alerts/review-queue", headers=_headers(doctor.id))

    assert response.status_code == 200, response.text
    assert queue.status_code == 200
    row = next(item for item in queue.json() if item["alert_id"] == alert.id)
    assert row["last_action"] == "ACKNOWLEDGE"
    db_session.refresh(alert)
    assert alert.status == original_status
