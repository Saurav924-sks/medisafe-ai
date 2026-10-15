from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Mapping

from sqlalchemy.engine import make_url

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings


STAGING_CONFIRMATION = "CREATE_SYNTHETIC_STAGING_CLINICIANS"
STAGING_ORGANIZATION_NAME = "Synthetic MediSafe Staging Organization"
STAGING_CLINICIANS = (
    {
        "key": "admin",
        "email": "synthetic-staging-admin@example.invalid",
        "display_name": "Synthetic Staging Admin Clinician",
        "roles": ("ADMIN", "DOCTOR"),
    },
    {
        "key": "read_only",
        "email": "synthetic-staging-readonly@example.invalid",
        "display_name": "Synthetic Staging Read-only Clinician",
        "roles": ("READ_ONLY",),
    },
)
REQUIRED_ROLES = {
    "ADMIN": "Staging administrator",
    "DOCTOR": "Staging prescriber",
    "PHARMACIST": "Staging pharmacist",
    "CLINICAL_REVIEWER": "Staging clinical reviewer",
    "READ_ONLY": "Staging read-only user",
}


def validate_staging_target(
    environment: Mapping[str, str],
    database_url: str | None,
) -> None:
    validate_staging_environment(environment)
    if not database_url:
        raise RuntimeError("An explicit PostgreSQL DATABASE_URL is required.")
    try:
        parsed_url = make_url(database_url)
    except Exception as exc:
        raise RuntimeError("DATABASE_URL is invalid for staging bootstrap.") from exc
    if parsed_url.get_backend_name() != "postgresql":
        raise RuntimeError("Staging bootstrap only supports a dedicated PostgreSQL database.")
    expected_database = environment.get("MEDISAFE_STAGING_DATABASE_NAME", "").strip()
    if not expected_database or parsed_url.database != expected_database:
        raise RuntimeError(
            "DATABASE_URL database name must match MEDISAFE_STAGING_DATABASE_NAME."
        )


def validate_staging_environment(environment: Mapping[str, str]) -> None:
    app_environment = environment.get("APP_ENV", "").strip().lower()
    if app_environment == "production":
        raise RuntimeError("Staging bootstrap is prohibited in production.")
    if app_environment != "staging":
        raise RuntimeError("Set APP_ENV=staging before running the staging bootstrap.")
    if environment.get("MEDISAFE_STAGING_SEED_CONFIRM") != STAGING_CONFIRMATION:
        raise RuntimeError("Explicit staging seed confirmation is required.")


def seed_staging_records(db) -> dict[str, int]:
    from app.models.clinical import Organization, Role, User, UserRole

    organization = (
        db.query(Organization)
        .filter(Organization.name == STAGING_ORGANIZATION_NAME)
        .one_or_none()
    )
    if organization is None:
        organization = Organization(name=STAGING_ORGANIZATION_NAME, is_active=True)
        db.add(organization)
        db.flush()
    elif not organization.is_active:
        raise RuntimeError("The existing synthetic staging organization is inactive; refusing to modify it.")

    roles: dict[str, Role] = {}
    for name, description in REQUIRED_ROLES.items():
        role = db.query(Role).filter(Role.name == name).one_or_none()
        if role is None:
            role = Role(name=name, description=description, is_active=True)
            db.add(role)
            db.flush()
        elif not role.is_active:
            raise RuntimeError(f"The existing {name} role is inactive; refusing to modify it.")
        roles[name] = role

    clinician_ids: dict[str, int] = {}
    for definition in STAGING_CLINICIANS:
        clinician = (
            db.query(User)
            .filter(
                User.organization_id == organization.id,
                User.email_normalized == definition["email"],
            )
            .one_or_none()
        )
        if clinician is None:
            clinician = User(
                organization_id=organization.id,
                email=definition["email"],
                email_normalized=definition["email"],
                display_name=definition["display_name"],
                is_active=True,
            )
            db.add(clinician)
            db.flush()
        elif not clinician.is_active or clinician.display_name != definition["display_name"]:
            raise RuntimeError(
                "An existing synthetic staging clinician is inactive or has unexpected "
                "attributes; refusing to modify it."
            )

        expected_role_ids = {roles[name].id for name in definition["roles"]}
        existing_role_ids = {
            role_id
            for (role_id,) in db.query(UserRole.role_id)
            .filter(UserRole.user_id == clinician.id)
            .all()
        }
        if existing_role_ids - expected_role_ids:
            raise RuntimeError(
                "An existing synthetic staging clinician has unexpected role assignments; "
                "refusing to modify them."
            )
        for role_name in definition["roles"]:
            if roles[role_name].id not in existing_role_ids:
                db.add(UserRole(user_id=clinician.id, role_id=roles[role_name].id))
        clinician_ids[definition["key"]] = clinician.id

    return clinician_ids


def main() -> None:
    validate_staging_environment(os.environ)
    validate_staging_target(os.environ, settings.DATABASE_URL)
    from app.core.database import SessionLocal

    with SessionLocal() as db:
        try:
            clinician_ids = seed_staging_records(db)
            db.commit()
        except Exception:
            db.rollback()
            raise
    print(f"Synthetic staging admin/prescriber clinician ID: {clinician_ids['admin']}")
    print(f"Synthetic staging read-only clinician ID: {clinician_ids['read_only']}")
    print("No patient, prescription, or knowledge-base records were created or activated.")


if __name__ == "__main__":
    main()
