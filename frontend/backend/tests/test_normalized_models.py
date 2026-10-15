import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.clinical import (
    Allergy,
    AllergyChange,
    AllergyDataStatus,
    Analysis,
    AnalysisStatus,
    AuditEvent,
    DataStatus,
    Organization,
    PatientIdentifier,
    PregnancyStatus,
    Role,
)
from app.models.models import Patient


@pytest.fixture
def db_engine():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_normalized_entities_and_explicit_unknown_states(db_engine):
    tables = set(inspect(db_engine).get_table_names())
    assert {
        "organizations", "users", "roles", "user_roles", "patients",
        "patient_identifiers", "encounters", "observations", "allergies",
        "allergy_changes", "conditions", "medications", "medication_ingredients",
        "medication_history", "medication_orders", "prescriptions", "analyses",
        "analysis_rule_usages", "alerts", "clinical_rules", "knowledge_versions",
        "feedback", "audit_events",
    } <= tables

    with Session(db_engine) as session:
        organization = Organization(name="Synthetic Test Organization")
        session.add(organization)
        session.flush()
        patient = Patient(name="Synthetic Test Patient", age=40, gender="unknown")
        session.add(patient)
        session.flush()

        assert patient.organization_id == 1
        assert patient.allergy_data_status is AllergyDataStatus.NOT_AVAILABLE
        assert patient.renal_function_status is DataStatus.NOT_AVAILABLE
        assert patient.pregnancy_status is PregnancyStatus.NOT_AVAILABLE

        analysis = Analysis(organization_id=organization.id, patient_id=patient.id)
        session.add(analysis)
        session.flush()
        assert analysis.status is AnalysisStatus.INCOMPLETE
        assert not analysis.allergy_checked
        assert not analysis.renal_checked


def test_mrn_is_unique_within_organization(db_engine):
    with Session(db_engine) as session:
        organization = Organization(name="Synthetic Test Organization")
        session.add(organization)
        session.flush()
        first = Patient(name="Synthetic Test Patient A", age=30, gender="unknown")
        second = Patient(name="Synthetic Test Patient B", age=31, gender="unknown")
        session.add_all([first, second])
        session.flush()
        session.add_all([
            PatientIdentifier(
                organization_id=organization.id, patient_id=first.id,
                identifier_type="MRN", value="MRN-TEST-001", normalized_value="MRN-TEST-001",
            ),
            PatientIdentifier(
                organization_id=organization.id, patient_id=second.id,
                identifier_type="MRN", value="MRN-TEST-001", normalized_value="MRN-TEST-001",
            ),
        ])
        with pytest.raises(IntegrityError):
            session.flush()


def test_allergy_changes_are_recorded_and_audit_events_are_append_only(db_engine):
    with Session(db_engine) as session:
        organization = Organization(name="Synthetic Test Organization")
        session.add(organization)
        session.flush()
        patient = Patient(name="Synthetic Test Patient", age=40, gender="unknown")
        session.add(patient)
        session.flush()

        allergy = Allergy(
            organization_id=organization.id,
            patient_id=patient.id,
            substance="Synthetic Test Substance",
        )
        session.add(allergy)
        session.flush()
        allergy.notes = "Updated synthetic note"
        session.flush()

        changes = session.query(AllergyChange).filter_by(allergy_id=allergy.id).all()
        assert [change.change_type for change in changes] == ["CREATED", "UPDATED"]
        assert changes[1].changed_fields["notes"]["new"] == "Updated synthetic note"

        event = AuditEvent(action="CREATE", entity_type="Patient", entity_id=str(patient.id))
        session.add(event)
        session.flush()
        event.action = "UPDATE"
        with pytest.raises(ValueError, match="append-only"):
            session.flush()
        session.rollback()


def test_clinical_records_cannot_be_hard_deleted(db_engine):
    with Session(db_engine) as session:
        organization = Organization(name="Synthetic Test Organization")
        session.add(organization)
        session.flush()
        role = Role(name="READ_ONLY")
        session.add(role)
        session.flush()
        with pytest.raises(ValueError, match="Hard deletion is disabled"):
            session.delete(role)
            session.flush()
