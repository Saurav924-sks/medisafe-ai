import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = BACKEND_ROOT / "alembic.ini"
MIGRATION_DIR = BACKEND_ROOT / "migrations"
LEGACY_TABLES = (
    "patients",
    "patient_allergies",
    "patient_conditions",
    "patient_medications",
    "prescriptions",
    "prescription_items",
    "alert_feedback",
    "audit_logs",
)


def _upgrade(connection):
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(MIGRATION_DIR))
    config.attributes["connection"] = connection
    command.upgrade(config, "head")
    return config


def _legacy_counts(connection):
    inspector = inspect(connection)
    return {
        table: connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
        for table in LEGACY_TABLES
        if table in inspector.get_table_names()
    }


def test_clean_database_migrates_and_seeds_only_system_reference_rows():
    engine = create_engine("sqlite://")
    try:
        with engine.connect() as connection:
            config = _upgrade(connection)
            command.check(config)
            tables = set(inspect(connection).get_table_names())
            assert {
                "organizations", "users", "roles", "patients", "patient_identifiers",
                "encounters", "observations", "allergies", "conditions", "medications",
                "medication_ingredients", "medication_history", "medication_orders",
                "prescriptions", "analyses", "alerts", "clinical_rules",
                "knowledge_versions", "feedback", "audit_events",
            } <= tables
            assert connection.execute(text("SELECT name FROM organizations WHERE id = 1")).scalar_one() == "Default Organization"
            assert connection.execute(text("SELECT COUNT(*) FROM roles")).scalar_one() == 5
            assert connection.execute(text("SELECT COUNT(*) FROM patients")).scalar_one() == 0
            version1 = connection.execute(text(
                "SELECT version, source, source_version, effective_date, last_reviewed, evidence_reference, checksum, lifecycle_stage, review_note, payload "
                "FROM knowledge_versions WHERE dataset = 'medisafe-clinical' AND version = '1'"
            )).one()
            assert version1[0:5] == (
                "1", "Existing prototype knowledge graph", "legacy-unversioned", None, None,
            )
            assert version1[5] and version1[6].startswith("sha256:")
            assert version1[7:9] == ("REVIEW_PENDING", "prototype data — not clinically reviewed")
            assert "drug_drug_interactions" in version1[9]
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    finally:
        engine.dispose()


def test_unversioned_legacy_schema_backfills_without_deleting_rows():
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE patients (id INTEGER PRIMARY KEY, name VARCHAR, age INTEGER, gender VARCHAR)")
            connection.exec_driver_sql("CREATE TABLE patient_allergies (id INTEGER PRIMARY KEY, patient_id INTEGER, allergy_name VARCHAR)")
            connection.exec_driver_sql("CREATE TABLE patient_conditions (id INTEGER PRIMARY KEY, patient_id INTEGER, condition_name VARCHAR)")
            connection.exec_driver_sql("CREATE TABLE patient_medications (id INTEGER PRIMARY KEY, patient_id INTEGER, medication_name VARCHAR, dose VARCHAR, frequency VARCHAR)")
            connection.exec_driver_sql("CREATE TABLE prescriptions (id INTEGER PRIMARY KEY, patient_id INTEGER, raw_text TEXT, created_at VARCHAR)")
            connection.exec_driver_sql("CREATE TABLE prescription_items (id INTEGER PRIMARY KEY, prescription_id INTEGER, drug_name VARCHAR, dose VARCHAR, unit VARCHAR, frequency VARCHAR, duration VARCHAR)")
            connection.exec_driver_sql("CREATE TABLE alert_feedback (id INTEGER PRIMARY KEY, analysis_id INTEGER, alert_index INTEGER NOT NULL, override_decision BOOLEAN, clinician_note TEXT, created_at DATETIME)")
            connection.exec_driver_sql("INSERT INTO patients VALUES (7, 'Synthetic Test Patient', 42, 'unknown')")
            connection.exec_driver_sql("INSERT INTO patient_allergies VALUES (11, 7, 'Synthetic Test Substance')")
            connection.exec_driver_sql("INSERT INTO patient_conditions VALUES (12, 7, 'Synthetic Test Condition')")
            connection.exec_driver_sql("INSERT INTO patient_medications VALUES (13, 7, 'Synthetic Test Medication', NULL, NULL)")
            connection.exec_driver_sql("INSERT INTO prescriptions VALUES (17, 7, 'Synthetic text', '2024-01-01')")
            connection.exec_driver_sql("INSERT INTO prescription_items VALUES (19, 17, 'Synthetic Test Medication', NULL, NULL, NULL, NULL)")
            connection.exec_driver_sql("INSERT INTO alert_feedback VALUES (23, 17, 0, NULL, NULL, NULL)")

        with engine.connect() as connection:
            before = _legacy_counts(connection)
            _upgrade(connection)
            after = _legacy_counts(connection)
            assert {table: after[table] for table in before} == before
            assert connection.execute(text("SELECT organization_id, allergy_data_status, renal_function_status, pregnancy_status FROM patients WHERE id = 7")).one() == (1, "UNKNOWN", "NOT_AVAILABLE", "NOT_AVAILABLE")
            assert connection.execute(text("SELECT verification_status, clinical_status FROM allergies WHERE id = 11")).one() == ("UNKNOWN", "UNKNOWN")
            assert connection.execute(text("SELECT clinical_status FROM conditions WHERE id = 12")).scalar_one() == "UNKNOWN"
            assert connection.execute(text("SELECT status, last_verified_at FROM medication_history WHERE id = 13")).one() == ("UNKNOWN", None)
            assert connection.execute(text("SELECT status, prescription_id FROM analyses WHERE id = 17")).one() == ("INCOMPLETE", 17)
            assert connection.execute(text("SELECT COUNT(*) FROM medication_orders WHERE legacy_item_id = 19")).scalar_one() == 1
            assert connection.execute(text("SELECT decision, legacy_feedback_id FROM feedback WHERE legacy_feedback_id = 23")).one() == ("UNKNOWN", 23)
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    finally:
        engine.dispose()


def test_existing_dev_database_copy_migrates_without_legacy_row_loss(tmp_path):
    source = BACKEND_ROOT / "medisafe.db"
    if not source.exists():
        pytest.skip("No local dev database is present; synthetic legacy migration test covers this path.")

    target = tmp_path / "medisafe-copy.db"
    with sqlite3.connect(source) as source_connection, sqlite3.connect(target) as target_connection:
        source_connection.backup(target_connection)

    engine = create_engine(f"sqlite:///{target.as_posix()}")
    try:
        with engine.connect() as connection:
            before = _legacy_counts(connection)
            _upgrade(connection)
            after = _legacy_counts(connection)
            assert {table: after[table] for table in before} == before
            assert "analyses" in inspect(connection).get_table_names()
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    finally:
        engine.dispose()

