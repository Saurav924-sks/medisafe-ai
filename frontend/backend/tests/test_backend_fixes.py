import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

import app.api.routes as routes
import app.core.audit_middleware as audit_middleware
import main
from app.models import models
from app.models.audit import AuditLog
from app.models.clinical import (
    DataStatus,
    Encounter,
    Medication,
    MedicationHistory,
    MedicationOrderStatus,
    MedicationStatus,
    Observation,
    Organization,
    Role,
    User,
    UserRole,
)

API_KEY = "synthetic-test-api-key"
ORG_A_HEADERS = {"X-API-Key": API_KEY, "X-Clinician-ID": "2"}


def _add_clinician(db_session, organization_id, role_name="DOCTOR"):
    role = db_session.query(Role).filter(Role.name == role_name).one()
    clinician = User(
        organization_id=organization_id,
        email=f"synthetic-{role_name.lower()}-{organization_id}@tests.invalid",
        email_normalized=f"synthetic-{role_name.lower()}-{organization_id}@tests.invalid",
        display_name=f"Synthetic {role_name} Clinician",
    )
    db_session.add(clinician)
    db_session.flush()
    db_session.add(UserRole(user_id=clinician.id, role_id=role.id))
    db_session.commit()
    return clinician


def _add_patient(db_session, organization_id, name="Synthetic Scoped Patient"):
    patient = models.Patient(
        organization_id=organization_id,
        name=name,
        age=42,
        gender="Unknown",
    )
    db_session.add(patient)
    db_session.commit()
    return patient


def test_create_patient_is_scoped_to_clinicians_organization(client, db_session):
    organization_b = Organization(name="Synthetic Organization B")
    db_session.add(organization_b)
    db_session.flush()
    clinician_b = _add_clinician(db_session, organization_b.id)
    headers_b = {"X-API-Key": API_KEY, "X-Clinician-ID": str(clinician_b.id)}

    created = client.post(
        "/api/v1/patients",
        json={"name": "Synthetic Org B Patient", "age": 42, "gender": "Unknown"},
        headers=headers_b,
    )
    assert created.status_code == 200, created.text
    patient_id = created.json()["id"]

    visible_to_b = client.get("/api/v1/patients", headers=headers_b)
    visible_to_a = client.get("/api/v1/patients", headers=ORG_A_HEADERS)
    assert [patient["id"] for patient in visible_to_b.json()] == [patient_id]
    assert visible_to_a.status_code == 200
    assert patient_id not in {patient["id"] for patient in visible_to_a.json()}
    assert client.get(f"/api/v1/patients/{patient_id}", headers=ORG_A_HEADERS).status_code == 404


def test_audit_uses_validated_clinician_id_and_never_logs_query_string(
    client, db_session, monkeypatch
):
    monkeypatch.setattr(audit_middleware, "SessionLocal", lambda: db_session)

    response = client.get(
        "/api/v1/patients?private_filter=synthetic-sensitive-value",
        headers=ORG_A_HEADERS,
    )
    assert response.status_code == 200
    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "GET /api/v1/patients")
        .one()
    )
    assert audit_entry.user_id == "2"
    assert "private_filter" not in audit_entry.details
    assert "synthetic-sensitive-value" not in audit_entry.details
    assert "?" not in audit_entry.action


def test_audit_uses_anonymous_when_request_has_no_validated_clinician(
    client, db_session, monkeypatch
):
    monkeypatch.setattr(audit_middleware, "SessionLocal", lambda: db_session)

    response = client.get("/api/v1/patients?private_filter=do-not-log")
    assert response.status_code == 401
    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "GET /api/v1/patients")
        .one()
    )
    assert audit_entry.user_id == "anonymous"
    assert "do-not-log" not in audit_entry.details


def test_health_executes_select_one(client, monkeypatch):
    executed = []

    class Connection:
        def execute(self, statement):
            executed.append(str(statement))

    class Engine:
        @contextmanager
        def connect(self):
            yield Connection()

    monkeypatch.setattr(main, "engine", Engine())
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "database": "connected"}
    assert executed == ["SELECT 1"]


def test_health_returns_503_when_database_check_fails(client, monkeypatch):
    class Engine:
        @contextmanager
        def connect(self):
            raise RuntimeError("synthetic database failure")
            yield

    monkeypatch.setattr(main, "engine", Engine())
    response = client.get("/api/health")

    assert response.status_code == 503
    assert response.json() == {"status": "unhealthy", "database": "disconnected"}


def test_system_status_uses_configured_version_and_live_checks(client, monkeypatch):
    class Engine:
        @contextmanager
        def connect(self):
            yield SimpleNamespace(execute=lambda statement: None)

    monkeypatch.setattr(routes, "engine", Engine())
    monkeypatch.setattr(routes.settings, "VERSION", "synthetic-test-version")
    monkeypatch.setattr(routes, "nlp", lambda _: object())

    response = client.get("/api/v1/system/status")

    assert response.status_code == 200
    result = response.json()
    assert result["version"] == "synthetic-test-version"
    assert result["database"] == "Connected"
    assert result["services"] == {"nlp_engine": "available"}
    assert "MedicalGrade" not in json.dumps(result)
    assert "Operational" not in json.dumps(result)


def test_system_status_reports_failed_database_and_nlp_checks(client, monkeypatch):
    class Engine:
        @contextmanager
        def connect(self):
            raise RuntimeError("synthetic database failure")
            yield

    def failed_nlp_check(_):
        raise RuntimeError("synthetic NLP failure")

    monkeypatch.setattr(routes, "engine", Engine())
    monkeypatch.setattr(routes, "nlp", failed_nlp_check)

    response = client.get("/api/v1/system/status")

    assert response.status_code == 200
    assert response.json()["database"] == "Disconnected"
    assert response.json()["services"] == {"nlp_engine": "unavailable"}


@pytest.mark.parametrize(
    ("route_suffix", "resource_type"),
    [
        ("medication-history", "medication_history"),
        ("observations", "observations"),
        ("encounters", "encounters"),
        ("prescriptions", "prescriptions"),
    ],
)
def test_patient_read_endpoints_require_role_and_scope_to_organization(
    client, db_session, route_suffix, resource_type
):
    patient_a = _add_patient(db_session, 1, "Synthetic Patient A")
    patient_b = _add_patient(db_session, 1, "Synthetic Patient B")
    other_organization = Organization(name=f"Synthetic {route_suffix} Organization B")
    db_session.add(other_organization)
    db_session.flush()
    patient_other_org = _add_patient(db_session, other_organization.id)

    if resource_type == "medication_history":
        medication = Medication(
            name="Synthetic Test Medication",
            normalized_name=f"synthetic test medication {route_suffix}",
            catalog_status=DataStatus.KNOWN,
        )
        db_session.add(medication)
        db_session.flush()
        record = MedicationHistory(
            organization_id=1,
            patient_id=patient_a.id,
            medication_id=medication.id,
            medication_name_snapshot="Synthetic Test Medication",
            status=MedicationStatus.UNKNOWN,
        )
    elif resource_type == "observations":
        record = Observation(
            organization_id=1,
            patient_id=patient_a.id,
            code="synthetic-test-code",
            availability_status=DataStatus.NOT_AVAILABLE,
        )
    elif resource_type == "encounters":
        record = Encounter(
            organization_id=1,
            patient_id=patient_a.id,
            status="UNKNOWN",
        )
    else:
        record = models.Prescription(
            organization_id=1,
            patient_id=patient_a.id,
            status=MedicationOrderStatus.UNKNOWN,
            parser_status="TEST",
        )
    db_session.add(record)
    db_session.commit()

    path = f"/api/v1/patients/{patient_a.id}/{route_suffix}"
    response = client.get(path, headers=ORG_A_HEADERS)
    assert response.status_code == 200, response.text
    assert len(response.json()) == 1
    assert response.json()[0]["patient_id"] == patient_a.id
    assert response.json()[0]["id"] == record.id

    assert client.get(path).status_code == 401
    no_role_clinician = User(
        organization_id=1,
        email=f"synthetic-no-role-{route_suffix}@tests.invalid",
        email_normalized=f"synthetic-no-role-{route_suffix}@tests.invalid",
        display_name="Synthetic Clinician Without Role",
    )
    db_session.add(no_role_clinician)
    db_session.commit()
    no_role_headers = {
        "X-API-Key": API_KEY,
        "X-Clinician-ID": str(no_role_clinician.id),
    }
    assert client.get(path, headers=no_role_headers).status_code == 403
    assert client.get(
        f"/api/v1/patients/{patient_other_org.id}/{route_suffix}",
        headers=ORG_A_HEADERS,
    ).status_code == 404
    assert client.get(
        f"/api/v1/patients/{patient_b.id}/{route_suffix}",
        headers=ORG_A_HEADERS,
    ).json() == []


def test_cors_origins_are_configurable_and_have_localhost_defaults(monkeypatch):
    monkeypatch.setattr(
        main.settings,
        "CORS_ORIGINS",
        "https://frontend.example.invalid, http://localhost:5173 ,,",
    )
    assert main.get_cors_origins() == [
        "https://frontend.example.invalid",
        "http://localhost:5173",
    ]

    monkeypatch.setattr(main.settings, "CORS_ORIGINS", "")
    assert main.get_cors_origins() == [
        "http://localhost:5173",
        "http://localhost:3000",
    ]


def test_cors_middleware_allows_configured_origin_and_rejects_others(client):
    allowed = client.get(
        "/api/health",
        headers={"Origin": "http://localhost:5173"},
    )
    disallowed = client.get(
        "/api/health",
        headers={"Origin": "https://untrusted.example.invalid"},
    )

    assert allowed.status_code == 200
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert disallowed.status_code == 200
    assert "access-control-allow-origin" not in disallowed.headers


def test_cors_configuration_rejects_wildcard_origin(monkeypatch):
    monkeypatch.setattr(main.settings, "CORS_ORIGINS", "*")

    with pytest.raises(ValueError, match="explicit HTTP"):
        main.get_cors_origins()


def test_hosted_cors_requires_an_explicit_origin(monkeypatch):
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("CORS_ORIGINS", "")

    with pytest.raises(RuntimeError, match="explicitly include"):
        main.get_cors_origins()


def test_render_postgres_url_override_is_normalized(monkeypatch):
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgres://db.example.invalid/medisafe",
    )

    assert main.settings.DATABASE_URL == (
        "postgresql+psycopg2://db.example.invalid/medisafe"
    )


def test_hosted_database_rejects_sqlite_and_requires_explicit_url(monkeypatch):
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./synthetic-local.db")
    with pytest.raises(ValueError, match="require a PostgreSQL"):
        _ = main.settings.DATABASE_URL

    monkeypatch.delenv("DATABASE_URL")
    monkeypatch.setattr(main.settings, "database_url_override", None)
    with pytest.raises(ValueError, match="must be explicitly configured"):
        _ = main.settings.DATABASE_URL
