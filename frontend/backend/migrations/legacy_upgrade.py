"""Data-preserving upgrade path for the pre-Alembic MediSafe schema."""
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text

from app.core.database import Base
from app.models.clinical import (
    AllergyCategory,
    AllergyClinicalStatus,
    AnalysisStatus,
    ClinicalSeverity,
    DataStatus,
    FeedbackDecision,
    KnowledgeStatus,
    MedicationOrderStatus,
    MedicationStatus,
    PregnancyStatus,
    VerificationStatus,
)
from app.models.models import Patient


def _add_legacy_columns(connection, table_name, columns):
    inspector = inspect(connection)
    if table_name not in inspector.get_table_names():
        return
    present = {column["name"] for column in inspector.get_columns(table_name)}
    missing = [(name, column) for name, column in columns.items() if name not in present]
    if not missing:
        return
    with op.batch_alter_table(table_name, recreate="always") as batch:
        for name, column in missing:
            batch.add_column(column)
        if table_name == "patients" and "organization_id" in {name for name, _ in missing}:
            batch.create_foreign_key(
                "fk_patients_organization_id_organizations",
                "organizations",
                ["organization_id"],
                ["id"],
                ondelete="RESTRICT",
            )
        if table_name == "prescriptions" and "organization_id" in {name for name, _ in missing}:
            batch.create_foreign_key(
                "fk_prescriptions_organization_id_organizations",
                "organizations",
                ["organization_id"],
                ["id"],
                ondelete="RESTRICT",
            )
        for column_name, _column in missing:
            if column_name in {"created_by", "updated_by", "deactivated_by"}:
                batch.create_foreign_key(
                    f"fk_{table_name}_{column_name}_users",
                    "users",
                    [column_name],
                    ["id"],
                    ondelete="RESTRICT",
                )


def _common_legacy_columns():
    return {
        "updated_at": sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        "created_by": sa.Column("created_by", sa.Integer(), nullable=True),
        "updated_by": sa.Column("updated_by", sa.Integer(), nullable=True),
        "is_active": sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        "deactivated_at": sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        "deactivated_by": sa.Column("deactivated_by", sa.Integer(), nullable=True),
    }


def _rows(connection, query):
    return [dict(row) for row in connection.execute(text(query)).mappings()]


def _insert_rows(connection, table_name, rows):
    if rows:
        connection.execute(Base.metadata.tables[table_name].insert(), rows)


def upgrade_legacy_schema():
    connection = op.get_bind()

    # Create only the new tables; SQLAlchemy leaves every pre-existing table and row intact.
    Base.metadata.create_all(connection, checkfirst=True)

    organization = connection.execute(
        text("SELECT id FROM organizations WHERE id = 1")
    ).first()
    if not organization:
        connection.execute(
            Base.metadata.tables["organizations"].insert().values(
                id=1, name="Default Organization", is_active=True,
            )
        )

    roles = Base.metadata.tables["roles"]
    for role_name in ("ADMIN", "DOCTOR", "PHARMACIST", "CLINICAL_REVIEWER", "READ_ONLY"):
        if not connection.execute(text("SELECT 1 FROM roles WHERE name = :name"), {"name": role_name}).first():
            connection.execute(roles.insert().values(name=role_name))

    patient_columns = {
        "organization_id": sa.Column("organization_id", sa.Integer(), nullable=True),
        "allergy_data_status": sa.Column("allergy_data_status", sa.String(32), nullable=False, server_default="UNKNOWN"),
        "renal_function_status": sa.Column("renal_function_status", sa.String(32), nullable=False, server_default=DataStatus.NOT_AVAILABLE.value),
        "pregnancy_status": sa.Column("pregnancy_status", sa.String(32), nullable=False, server_default=PregnancyStatus.NOT_AVAILABLE.value),
        "created_at": sa.Column("created_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()),
        **_common_legacy_columns(),
    }
    _add_legacy_columns(connection, "patients", patient_columns)

    prescription_columns = {
        "organization_id": sa.Column("organization_id", sa.Integer(), nullable=True),
        "encounter_id": sa.Column("encounter_id", sa.Integer(), nullable=True),
        "status": sa.Column("status", sa.String(32), nullable=False, server_default=MedicationOrderStatus.UNKNOWN.value),
        "source": sa.Column("source", sa.String(120), nullable=True),
        **_common_legacy_columns(),
    }
    _add_legacy_columns(connection, "prescriptions", prescription_columns)

    for table_name in (
        "patient_allergies", "patient_conditions", "patient_medications",
        "prescription_items", "alert_feedback",
    ):
        columns = _common_legacy_columns()
        if table_name in {"patient_allergies", "patient_conditions", "patient_medications", "prescription_items"}:
            columns["created_at"] = sa.Column("created_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now())
        if table_name == "alert_feedback":
            columns["organization_id"] = sa.Column("organization_id", sa.Integer(), nullable=True)
            columns["alert_type"] = sa.Column("alert_type", sa.String(100), nullable=True)
            columns["drug_name"] = sa.Column("drug_name", sa.String(100), nullable=True)
        _add_legacy_columns(connection, table_name, columns)

    connection.execute(text("UPDATE patients SET organization_id = 1 WHERE organization_id IS NULL"))
    connection.execute(text("UPDATE prescriptions SET organization_id = 1 WHERE organization_id IS NULL"))
    connection.execute(text("UPDATE patient_allergies SET is_active = 1 WHERE is_active IS NULL"))
    connection.execute(text("UPDATE patient_conditions SET is_active = 1 WHERE is_active IS NULL"))
    connection.execute(text("UPDATE patient_medications SET is_active = 1 WHERE is_active IS NULL"))
    connection.execute(text("UPDATE prescription_items SET is_active = 1 WHERE is_active IS NULL"))
    connection.execute(text("UPDATE alert_feedback SET organization_id = 1 WHERE organization_id IS NULL"))
    connection.execute(text("UPDATE alert_feedback SET is_active = 1 WHERE is_active IS NULL"))
    connection.execute(text("UPDATE patients SET allergy_data_status = 'UNKNOWN' WHERE allergy_data_status = 'NOT_AVAILABLE'"))
    connection.execute(text("UPDATE patients SET renal_function_status = 'NOT_AVAILABLE' WHERE renal_function_status IS NULL"))
    connection.execute(text("UPDATE patients SET pregnancy_status = 'NOT_AVAILABLE' WHERE pregnancy_status IS NULL"))

    default_knowledge = connection.execute(text(
        "SELECT id FROM knowledge_versions WHERE dataset = 'legacy' AND version = 'unversioned'"
    )).first()
    if default_knowledge:
        knowledge_version_id = default_knowledge[0]
    else:
        result = connection.execute(Base.metadata.tables["knowledge_versions"].insert().values(
            dataset="legacy",
            version="unversioned",
            source="Legacy local configuration; provenance unavailable",
            status=KnowledgeStatus.UNAVAILABLE.value,
            is_active=False,
        ))
        knowledge_version_id = result.inserted_primary_key[0]

    medications = {}
    medication_names = set()
    for row in _rows(connection, "SELECT medication_name FROM patient_medications WHERE medication_name IS NOT NULL"):
        if row["medication_name"].strip():
            medication_names.add(row["medication_name"].strip())
    for row in _rows(connection, "SELECT drug_name FROM prescription_items WHERE drug_name IS NOT NULL"):
        if row["drug_name"].strip():
            medication_names.add(row["drug_name"].strip())

    medication_table = Base.metadata.tables["medications"]
    for name in sorted(medication_names, key=str.casefold):
        normalized = name.casefold()
        record = connection.execute(text(
            "SELECT id FROM medications WHERE normalized_name = :normalized"
        ), {"normalized": normalized}).first()
        if record:
            medications[normalized] = record[0]
        else:
            result = connection.execute(medication_table.insert().values(
                name=name,
                normalized_name=normalized,
                catalog_status=DataStatus.UNKNOWN.value,
                source="LEGACY_MIGRATION",
                is_active=True,
            ))
            medications[normalized] = result.inserted_primary_key[0]

    allergy_rows = _rows(connection, """
        SELECT a.id, a.patient_id, a.allergy_name
        FROM patient_allergies AS a
        JOIN patients AS p ON p.id = a.patient_id
        WHERE a.allergy_name IS NOT NULL
    """)
    _insert_rows(connection, "allergies", [
        {
            "id": row["id"], "organization_id": 1, "patient_id": row["patient_id"],
            "substance": row["allergy_name"], "category": AllergyCategory.UNKNOWN.value,
            "severity": ClinicalSeverity.UNKNOWN.value,
            "clinical_status": AllergyClinicalStatus.UNKNOWN.value,
            "verification_status": VerificationStatus.UNKNOWN.value,
            "recorded_at": datetime.now(timezone.utc), "source": "LEGACY_MIGRATION",
        }
        for row in allergy_rows
    ])
    if allergy_rows:
        _insert_rows(connection, "allergy_changes", [
            {
                "allergy_id": row["id"], "change_type": "IMPORTED",
                "changed_fields": {"source": "legacy patient_allergies", "legacy_id": row["id"]},
            }
            for row in allergy_rows
        ])

    condition_rows = _rows(connection, """
        SELECT c.id, c.patient_id, c.condition_name
        FROM patient_conditions AS c
        JOIN patients AS p ON p.id = c.patient_id
        WHERE c.condition_name IS NOT NULL
    """)
    _insert_rows(connection, "conditions", [
        {
            "id": row["id"], "organization_id": 1, "patient_id": row["patient_id"],
            "name": row["condition_name"], "clinical_status": "UNKNOWN",
            "severity": ClinicalSeverity.UNKNOWN.value, "source": "LEGACY_MIGRATION",
        }
        for row in condition_rows
    ])

    for row in _rows(connection, """
        SELECT m.id, m.patient_id, m.medication_name, m.dose, m.frequency
        FROM patient_medications AS m
        JOIN patients AS p ON p.id = m.patient_id
        WHERE m.medication_name IS NOT NULL AND trim(m.medication_name) <> ''
    """):
        medication_id = medications[row["medication_name"].strip().casefold()]
        _insert_rows(connection, "medication_history", [{
            "id": row["id"], "organization_id": 1, "patient_id": row["patient_id"],
            "medication_id": medication_id, "status": MedicationStatus.UNKNOWN.value,
            "medication_name_snapshot": row["medication_name"], "dose": row["dose"],
            "frequency": row["frequency"], "source": "LEGACY_MIGRATION", "is_active": True,
        }])

    prescription_rows = _rows(connection, "SELECT id, patient_id FROM prescriptions WHERE patient_id IS NOT NULL")
    analysis_table = Base.metadata.tables["analyses"]
    for row in prescription_rows:
        exists = connection.execute(text("SELECT 1 FROM analyses WHERE prescription_id = :id"), {"id": row["id"]}).first()
        if not exists:
            connection.execute(analysis_table.insert().values(
                id=row["id"], organization_id=1, patient_id=row["patient_id"],
                prescription_id=row["id"], status=AnalysisStatus.INCOMPLETE.value,
                knowledge_version_id=knowledge_version_id, rule_set_version="unversioned",
                other_domains={},
            ))

    item_rows = _rows(connection, """
        SELECT i.id, i.prescription_id, i.drug_name, i.dose, i.unit, i.frequency, i.duration,
               p.patient_id
        FROM prescription_items AS i
        JOIN prescriptions AS p ON p.id = i.prescription_id
        WHERE i.drug_name IS NOT NULL AND trim(i.drug_name) <> ''
    """)
    order_table = Base.metadata.tables["medication_orders"]
    for row in item_rows:
        medication_id = medications[row["drug_name"].strip().casefold()]
        exists = connection.execute(text(
            "SELECT 1 FROM medication_orders WHERE legacy_item_id = :legacy_id"
        ), {"legacy_id": row["id"]}).first()
        if not exists:
            connection.execute(order_table.insert().values(
                organization_id=1, patient_id=row["patient_id"],
                prescription_id=row["prescription_id"], medication_id=medication_id,
                legacy_item_id=row["id"], medication_name_snapshot=row["drug_name"],
                dose=row["dose"], unit=row["unit"], frequency=row["frequency"],
                duration=row["duration"], status=MedicationOrderStatus.UNKNOWN.value,
                source="LEGACY_MIGRATION", is_active=True,
            ))

    feedback_columns = {column["name"] for column in inspect(connection).get_columns("alert_feedback")}
    selected = [name for name in (
        "id", "analysis_id", "alert_index", "alert_type", "drug_name",
        "override_decision", "clinician_note",
    ) if name in feedback_columns]
    feedback_rows = _rows(connection, f"SELECT {', '.join(selected)} FROM alert_feedback")
    feedback_table = Base.metadata.tables["feedback"]
    for row in feedback_rows:
        if not row.get("analysis_id"):
            continue
        exists = connection.execute(text(
            "SELECT 1 FROM feedback WHERE legacy_feedback_id = :legacy_id"
        ), {"legacy_id": row["id"]}).first() if "legacy_feedback_id" in feedback_table.c else None
        if exists:
            continue
        connection.execute(feedback_table.insert().values(
                organization_id=1, analysis_id=row["analysis_id"],
            legacy_feedback_id=row["id"], alert_index=row.get("alert_index"),
            legacy_alert_type=row.get("alert_type"), legacy_drug_name=row.get("drug_name"),
                decision=(FeedbackDecision.AGREE.value if row.get("override_decision") is True else
                          FeedbackDecision.DISAGREE.value if row.get("override_decision") is False else
                          FeedbackDecision.UNKNOWN.value),
                note=row.get("clinician_note"),
            ))
