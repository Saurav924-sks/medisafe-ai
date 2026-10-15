from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from app.core.schema_migrations import migrate_alert_feedback_columns
from app.models.models import AlertFeedback


def test_migrate_legacy_alert_feedback_table():
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                """
                CREATE TABLE alert_feedback (
                    id INTEGER PRIMARY KEY,
                    analysis_id INTEGER NOT NULL,
                    alert_index INTEGER NOT NULL,
                    override_decision BOOLEAN,
                    clinician_note TEXT,
                    created_at DATETIME
                )
                """
            )

        migrate_alert_feedback_columns(engine)
        # Migration must safely be repeatable at every startup.
        migrate_alert_feedback_columns(engine)

        columns = {column["name"] for column in inspect(engine).get_columns("alert_feedback")}
        assert {"alert_type", "drug_name"} <= columns

        with Session(engine) as session:
            session.add(AlertFeedback(
                analysis_id=1,
                alert_index=0,
                alert_type="Dosage Verification",
                drug_name="Amoxicillin",
            ))
            session.commit()
            saved = session.query(AlertFeedback).one()
            assert saved.alert_type == "Dosage Verification"
            assert saved.drug_name == "Amoxicillin"
    finally:
        engine.dispose()

