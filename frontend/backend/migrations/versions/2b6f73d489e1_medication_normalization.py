"""Store medication order routes and terminology outcomes."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "2b6f73d489e1"
down_revision: Union[str, None] = "36d36cba820f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _add_columns_if_missing(table_name: str, columns: list[sa.Column]) -> None:
    connection = op.get_bind()
    existing = {column["name"] for column in inspect(connection).get_columns(table_name)}
    for column in columns:
        if column.name not in existing:
            op.add_column(table_name, column)


def upgrade() -> None:
    _add_columns_if_missing("medication_ingredients", [
        sa.Column("source", sa.String(120), nullable=True),
    ])
    _add_columns_if_missing("prescriptions", [
        sa.Column("parser_status", sa.String(32), nullable=False, server_default="LEGACY_IMPORTED"),
    ])
    _add_columns_if_missing("medications", [
        sa.Column("strength_value", sa.Numeric(18, 6), nullable=True),
        sa.Column("strength_unit", sa.String(80), nullable=True),
        sa.Column("dose_form", sa.String(120), nullable=True),
        sa.Column("route", sa.String(80), nullable=True),
    ])
    _add_columns_if_missing("medication_orders", [
        sa.Column("route", sa.String(80), nullable=True),
        sa.Column("normalization_status", sa.String(32), nullable=False, server_default="NOT_AVAILABLE"),
        sa.Column("normalization_confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("match_method", sa.String(64), nullable=True),
        sa.Column("normalization_message", sa.String(200), nullable=True),
        sa.Column("normalization_result", sa.JSON(), nullable=True),
    ])

    check_name = "ck_medication_orders_normalization_status"
    connection = op.get_bind()
    checks = inspect(connection).get_check_constraints("medication_orders")
    if not any(check["name"] == check_name for check in checks):
        with op.batch_alter_table("medication_orders", recreate="always") as batch:
            batch.create_check_constraint(
                check_name,
                "normalization_status IN ('NORMALIZED', 'AMBIGUOUS', 'REVIEW_REQUIRED', 'UNKNOWN', 'NOT_AVAILABLE')",
            )


def downgrade() -> None:
    raise RuntimeError(
        "This migration is intentionally irreversible; normalization outcomes must not be discarded."
    )
