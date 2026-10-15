from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_ROOT)
sys.path.insert(0, str(BACKEND_ROOT))

from alembic import command
from alembic.config import Config

from app.core.config import settings
from app.core.database import SessionLocal, engine
from app.models.clinical import Organization, Role, User, UserRole


ORGANIZATION_NAME = "Synthetic Local Development Organization"
ROLE_DESCRIPTIONS = {
    "ADMIN": "Local development administrator",
    "DOCTOR": "Local development prescriber",
    "PHARMACIST": "Local development pharmacist",
    "CLINICAL_REVIEWER": "Local development clinical reviewer",
    "READ_ONLY": "Local development read-only user",
}
DEV_CLINICIANS = (
    {
        "key": "admin",
        "email": "dev-admin@local.invalid",
        "display_name": "Synthetic Dev Admin Clinician",
        "roles": ("ADMIN", "DOCTOR"),
    },
    {
        "key": "read_only",
        "email": "dev-readonly@local.invalid",
        "display_name": "Synthetic Dev Read-only Clinician",
        "roles": ("READ_ONLY",),
    },
)


def upgrade_database() -> None:
    if not settings.DATABASE_URL.startswith("sqlite:///"):
        raise RuntimeError(
            "The development seed refuses non-SQLite databases. "
            "Set DATABASE_URL=sqlite:///./medisafe-local.db in the repository .env."
        )

    migration_root = BACKEND_ROOT / "migrations"
    migration_config = Config(str(BACKEND_ROOT / "alembic.ini"))
    migration_config.set_main_option("script_location", str(migration_root))
    with engine.connect() as connection:
        migration_config.attributes["connection"] = connection
        command.upgrade(migration_config, "head")


def seed_development_records() -> dict[str, int]:
    with SessionLocal() as db:
        try:
            organization = (
                db.query(Organization)
                .filter(Organization.name == ORGANIZATION_NAME)
                .one_or_none()
            )
            if organization is None:
                organization = Organization(name=ORGANIZATION_NAME, is_active=True)
                db.add(organization)
                db.flush()
            else:
                organization.is_active = True

            roles: dict[str, Role] = {}
            for name, description in ROLE_DESCRIPTIONS.items():
                role = db.query(Role).filter(Role.name == name).one_or_none()
                if role is None:
                    role = Role(name=name, description=description, is_active=True)
                    db.add(role)
                    db.flush()
                else:
                    role.description = description
                    role.is_active = True
                roles[name] = role

            clinician_ids: dict[str, int] = {}
            for definition in DEV_CLINICIANS:
                email = definition["email"]
                clinician = (
                    db.query(User)
                    .filter(
                        User.organization_id == organization.id,
                        User.email_normalized == email,
                    )
                    .one_or_none()
                )
                if clinician is None:
                    clinician = User(
                        organization_id=organization.id,
                        email=email,
                        email_normalized=email,
                        display_name=definition["display_name"],
                        is_active=True,
                    )
                    db.add(clinician)
                    db.flush()
                else:
                    clinician.email = email
                    clinician.display_name = definition["display_name"]
                    clinician.is_active = True

                for role_name in definition["roles"]:
                    assignment = (
                        db.query(UserRole)
                        .filter(
                            UserRole.user_id == clinician.id,
                            UserRole.role_id == roles[role_name].id,
                        )
                        .one_or_none()
                    )
                    if assignment is None:
                        db.add(UserRole(user_id=clinician.id, role_id=roles[role_name].id))
                clinician_ids[definition["key"]] = clinician.id

            db.commit()
            return clinician_ids
        except Exception:
            db.rollback()
            raise


def main() -> None:
    upgrade_database()
    clinician_ids = seed_development_records()
    print(f"Admin/prescriber clinician ID: {clinician_ids['admin']}")
    print(f"Read-only clinician ID: {clinician_ids['read_only']}")
    print("Use the selected ID in the X-Clinician-ID request header.")
    print("Send X-API-Key from the local .env; the API key is not printed.")


if __name__ == "__main__":
    main()
