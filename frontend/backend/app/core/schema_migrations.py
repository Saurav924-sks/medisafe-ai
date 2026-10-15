from sqlalchemy import Engine, inspect, text


def migrate_alert_feedback_columns(engine: Engine) -> None:
    """Add feedback metadata columns to legacy databases created before they existed.

    ``Base.metadata.create_all`` creates missing tables, but does not alter existing
    tables. Keep this small, idempotent migration until a versioned Alembic migration
    is introduced.
    """
    inspector = inspect(engine)
    if "alert_feedback" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("alert_feedback")}
    additions = {
        "alert_type": "VARCHAR",
        "drug_name": "VARCHAR",
        "updated_at": "DATETIME",
        "created_by": "INTEGER",
        "updated_by": "INTEGER",
        "is_active": "BOOLEAN NOT NULL DEFAULT 1",
        "deactivated_at": "DATETIME",
        "deactivated_by": "INTEGER",
    }

    with engine.begin() as connection:
        for column_name, column_type in additions.items():
            if column_name not in existing_columns:
                connection.execute(text(
                    f"ALTER TABLE alert_feedback ADD COLUMN {column_name} {column_type}"
                ))
