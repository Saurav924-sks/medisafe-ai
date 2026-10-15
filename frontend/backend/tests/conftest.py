import os
import json
from datetime import date
from pathlib import Path

# Keep backend tests isolated from the PostgreSQL-only development environment.
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ["API_KEY"] = "synthetic-test-api-key"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.models.clinical import KnowledgeStatus, KnowledgeVersion, Organization, Role, User, UserRole
from main import app

# Use a shared in-memory SQLite database for testing
SQLALCHEMY_DATABASE_URL = "sqlite://"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture(scope="function")
def db_session():
    """Creates a fresh database for each test."""
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        organization = Organization(id=1, name="Synthetic Test Organization")
        session.add(organization)
        session.flush()
        reviewer_role = Role(name="CLINICAL_REVIEWER")
        doctor_role = Role(name="DOCTOR")
        reviewer = User(
            organization_id=organization.id,
            email="synthetic-reviewer@tests.invalid",
            email_normalized="synthetic-reviewer@tests.invalid",
            display_name="Synthetic Test Reviewer",
        )
        session.add_all([reviewer_role, reviewer])
        session.flush()
        session.add(UserRole(user_id=reviewer.id, role_id=reviewer_role.id))
        doctor = User(
            organization_id=organization.id,
            email="synthetic-doctor@tests.invalid",
            email_normalized="synthetic-doctor@tests.invalid",
            display_name="Synthetic Test Doctor",
        )
        session.add_all([doctor_role, doctor])
        session.flush()
        session.add(UserRole(user_id=doctor.id, role_id=doctor_role.id))
        artifact_path = Path(__file__).resolve().parents[2] / "knowledge_base" / "versions" / "v1.json"
        artifact = json.loads(artifact_path.read_text(encoding="utf-8-sig"))
        session.add(KnowledgeVersion(
            dataset="medisafe-clinical",
            version="fixture-v1",
            source="Synthetic test fixture",
            source_version="fixture-v1",
            effective_date=date(2026, 1, 1),
            last_reviewed=date(2026, 1, 1),
            checksum=artifact["manifest"]["checksum"],
            evidence_reference="Synthetic test fixture only",
            status=KnowledgeStatus.LOADED,
            lifecycle_stage="ACTIVE",
            reviewed_by=reviewer.id,
            activated_by=reviewer.id,
            payload=artifact["data"],
        ))
        session.commit()
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine) # Clean up after test

@pytest.fixture(scope="function")
def client(db_session):
    """Provides a FastAPI TestClient with the test database."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass
    
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()

