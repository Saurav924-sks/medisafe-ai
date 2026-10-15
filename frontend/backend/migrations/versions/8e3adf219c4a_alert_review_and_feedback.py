"""Add immutable alert review actions and versioned feedback."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "8e3adf219c4a"
down_revision: Union[str, None] = "2b6f73d489e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    columns = {column["name"] for column in inspect(connection).get_columns("feedback")}
    additions = [
        sa.Column("clinician_id", sa.Integer(), nullable=True),
        sa.Column("alert_type", sa.String(80), nullable=True),
        sa.Column(
            "feedback",
            sa.Enum("AGREE", "DISAGREE", "OVERRIDE", "UNKNOWN", name="alert_feedback_value", native_enum=False, create_constraint=True),
            nullable=True,
        ),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("rule_version", sa.String(80), nullable=True),
        sa.Column("knowledge_base_version", sa.String(80), nullable=True),
    ]
    missing = [column for column in additions if column.name not in columns]
    if missing:
        with op.batch_alter_table("feedback", recreate="always") as batch:
            for column in missing:
                batch.add_column(column)
            if "clinician_id" not in columns:
                batch.create_foreign_key(
                    "fk_feedback_clinician_id_users",
                    "users",
                    ["clinician_id"],
                    ["id"],
                    ondelete="RESTRICT",
                )

    if "alert_review_actions" not in inspect(connection).get_table_names():
        op.create_table(
            "alert_review_actions",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("organization_id", sa.Integer(), nullable=False),
            sa.Column("analysis_id", sa.Integer(), nullable=False),
            sa.Column("alert_id", sa.Integer(), nullable=False),
            sa.Column("clinician_id", sa.Integer(), nullable=False),
            sa.Column(
                "action",
                sa.Enum("REVIEW", "ACKNOWLEDGE", "OVERRIDE", "RESOLVE", "DISMISS", name="alert_review_action", native_enum=False, create_constraint=True),
                nullable=False,
            ),
            sa.Column(
                "override_reason",
                sa.Enum("CLINICAL_JUDGMENT", "PATIENT_CONTEXT_NOT_CAPTURED", "DUPLICATE_OR_ALREADY_ADDRESSED", "REFERENCE_DATA_ISSUE", "OTHER", name="alert_override_reason", native_enum=False, create_constraint=True),
                nullable=True,
            ),
            sa.Column("override_reason_text", sa.String(length=1000), nullable=True),
            sa.Column("note", sa.String(length=1000), nullable=True),
            sa.Column("rule_version", sa.String(length=80), nullable=True),
            sa.Column("knowledge_base_version", sa.String(length=80), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["analysis_id"], ["analyses.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["alert_id"], ["alerts.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["clinician_id"], ["users.id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("alert_review_actions") as batch:
            batch.create_index("ix_alert_review_actions_alert_time", ["alert_id", "created_at"], unique=False)
            batch.create_index("ix_alert_review_actions_analysis", ["analysis_id"], unique=False)


def downgrade() -> None:
    raise RuntimeError(
        "This migration is intentionally irreversible; deleting review and feedback records is prohibited."
    )
