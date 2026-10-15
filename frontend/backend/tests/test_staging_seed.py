import pytest

from app.models.clinical import KnowledgeVersion, Organization, Role, User, UserRole
from scripts.seed_staging import (
    STAGING_CONFIRMATION,
    STAGING_ORGANIZATION_NAME,
    seed_staging_records,
    validate_staging_target,
)


def test_staging_seed_requires_staging_confirmation_and_rejects_production():
    with pytest.raises(RuntimeError, match="prohibited in production"):
        validate_staging_target(
            {
                "APP_ENV": "production",
                "MEDISAFE_STAGING_SEED_CONFIRM": STAGING_CONFIRMATION,
                "MEDISAFE_STAGING_DATABASE_NAME": "synthetic_staging",
            },
            "postgresql://example.invalid/synthetic_staging",
        )

    with pytest.raises(RuntimeError, match="Explicit staging seed confirmation"):
        validate_staging_target(
            {
                "APP_ENV": "staging",
                "MEDISAFE_STAGING_DATABASE_NAME": "synthetic_staging",
            },
            "postgresql://example.invalid/synthetic_staging",
        )


def test_staging_seed_refuses_non_postgresql_database():
    with pytest.raises(RuntimeError, match="dedicated PostgreSQL"):
        validate_staging_target(
            {
                "APP_ENV": "staging",
                "MEDISAFE_STAGING_SEED_CONFIRM": STAGING_CONFIRMATION,
                "MEDISAFE_STAGING_DATABASE_NAME": "not-used",
            },
            "sqlite:///./not-used.db",
        )


def test_staging_seed_requires_database_name_to_match_explicit_guard():
    with pytest.raises(RuntimeError, match="must match"):
        validate_staging_target(
            {
                "APP_ENV": "staging",
                "MEDISAFE_STAGING_SEED_CONFIRM": STAGING_CONFIRMATION,
                "MEDISAFE_STAGING_DATABASE_NAME": "medisafe-production",
            },
            "postgresql://example.invalid/medisafe-staging",
        )


def test_staging_seed_is_idempotent_and_does_not_change_knowledge(client, db_session):
    knowledge_before = [
        (item.id, item.lifecycle_stage, item.status)
        for item in db_session.query(KnowledgeVersion).order_by(KnowledgeVersion.id)
    ]

    first_ids = seed_staging_records(db_session)
    db_session.flush()
    second_ids = seed_staging_records(db_session)
    db_session.flush()

    assert second_ids == first_ids
    organization = (
        db_session.query(Organization)
        .filter(Organization.name == STAGING_ORGANIZATION_NAME)
        .one()
    )
    assert organization.is_active
    assert (
        db_session.query(User)
        .filter(User.organization_id == organization.id)
        .count()
        == 2
    )
    assert (
        db_session.query(UserRole)
        .filter(UserRole.user_id.in_(first_ids.values()))
        .count()
        == 3
    )
    expected_roles = {
        "admin": {"ADMIN", "DOCTOR"},
        "read_only": {"READ_ONLY"},
    }
    for key, clinician_id in first_ids.items():
        clinician = db_session.query(User).filter_by(id=clinician_id, is_active=True).one()
        assigned_roles = {
            role_name
            for (role_name,) in db_session.query(Role.name)
            .join(UserRole, UserRole.role_id == Role.id)
            .filter(UserRole.user_id == clinician_id, Role.is_active.is_(True))
            .all()
        }
        assert clinician.organization_id == organization.id
        assert assigned_roles == expected_roles[key]
    assert [
        (item.id, item.lifecycle_stage, item.status)
        for item in db_session.query(KnowledgeVersion).order_by(KnowledgeVersion.id)
    ] == knowledge_before
