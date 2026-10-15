"""Add governed, versioned knowledge lifecycle and seed prototype v1."""
from pathlib import Path
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "5c7a3e1b9d42"
down_revision: Union[str, None] = "8e3adf219c4a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    existing = {column["name"] for column in inspect(connection).get_columns("knowledge_versions")}
    new_columns = [
        sa.Column("last_reviewed", sa.Date(), nullable=True),
        sa.Column("lifecycle_stage", sa.String(32), nullable=False, server_default="IMPORTED"),
        sa.Column("evidence_reference", sa.String(1000), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.Column("activated_by", sa.Integer(), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
    ]
    with op.batch_alter_table("knowledge_versions", recreate="always") as batch:
        for column in new_columns:
            if column.name not in existing:
                batch.add_column(column)
        if "reviewed_by" not in existing:
            batch.create_foreign_key("fk_knowledge_versions_reviewed_by_users", "users", ["reviewed_by"], ["id"], ondelete="RESTRICT")
        if "activated_by" not in existing:
            batch.create_foreign_key("fk_knowledge_versions_activated_by_users", "users", ["activated_by"], ["id"], ondelete="RESTRICT")
    indexes = {item["name"] for item in inspect(connection).get_indexes("knowledge_versions")}
    if "uq_knowledge_one_active_per_dataset" not in indexes:
        op.create_index(
            "uq_knowledge_one_active_per_dataset", "knowledge_versions", ["dataset"], unique=True,
            sqlite_where=sa.text("lifecycle_stage = 'ACTIVE'"),
            postgresql_where=sa.text("lifecycle_stage = 'ACTIVE'"),
        )

    artifact_path = Path(__file__).resolve().parents[3] / "knowledge_base" / "versions" / "v1.json"
    artifact = json.loads(artifact_path.read_text(encoding="utf-8-sig"))
    manifest = artifact["manifest"]
    knowledge_versions = sa.table(
        "knowledge_versions",
        sa.column("dataset", sa.String), sa.column("version", sa.String),
        sa.column("source", sa.String), sa.column("source_version", sa.String),
        sa.column("effective_date", sa.Date), sa.column("checksum", sa.String),
        sa.column("status", sa.String), sa.column("last_reviewed", sa.Date),
        sa.column("lifecycle_stage", sa.String), sa.column("evidence_reference", sa.String),
        sa.column("review_note", sa.Text), sa.column("payload", sa.JSON),
    )
    found = connection.execute(sa.select(knowledge_versions.c.dataset).where(
        knowledge_versions.c.dataset == manifest["dataset"],
        knowledge_versions.c.version == manifest["version"],
    )).first()
    if not found:
        connection.execute(knowledge_versions.insert().values(
            dataset=manifest["dataset"], version=manifest["version"],
            source=manifest["source"], source_version=manifest["source_version"],
            effective_date=manifest["effective_date"], checksum=manifest["checksum"],
            status="LOADED", last_reviewed=manifest["last_reviewed"],
            lifecycle_stage="REVIEW_PENDING", evidence_reference=manifest["evidence_reference"],
            review_note=manifest["review_note"], payload=artifact["data"],
        ))


def downgrade() -> None:
    raise RuntimeError("This migration is intentionally irreversible; knowledge provenance and review history must not be discarded.")
