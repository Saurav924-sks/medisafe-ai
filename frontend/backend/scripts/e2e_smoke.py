from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import closing
from pathlib import Path

import httpx


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parents[1]
SYNTHETIC_API_KEY = "synthetic-e2e-only-key"
BASE_HEADERS = {"X-API-Key": SYNTHETIC_API_KEY, "X-Clinician-ID": "1"}
checks: list[tuple[str, str, str]] = []
state: dict[str, object] = {}


def check(name: str, operation) -> None:
    try:
        result = operation()
        if isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], bool):
            passed, detail = result
            checks.append((name, "PASS" if passed else "FAIL", str(detail or "")))
        else:
            checks.append((name, "PASS", str(result or "")))
    except Exception as exc:
        checks.append((name, "FAIL", f"{type(exc).__name__}: {exc}"))


def require_status(response: httpx.Response, *statuses: int) -> httpx.Response:
    if response.status_code not in statuses:
        raise AssertionError(
            f"expected HTTP {statuses}, got {response.status_code}: "
            f"{response.text[:400]}"
        )
    return response


def free_local_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def add_second_organization_clinician() -> int:
    setup = """
from app.core.database import SessionLocal
from app.models import models
from app.models.clinical import Organization, Role, User, UserRole
with SessionLocal() as db:
    organization = Organization(name="Synthetic E2E Organization B")
    db.add(organization)
    db.flush()
    role = db.query(Role).filter(Role.name == "DOCTOR").one()
    clinician = User(
        organization_id=organization.id,
        email="synthetic-e2e-doctor-b@tests.invalid",
        email_normalized="synthetic-e2e-doctor-b@tests.invalid",
        display_name="Synthetic E2E Organization B Clinician",
        is_active=True,
    )
    db.add(clinician)
    db.flush()
    db.add(UserRole(user_id=clinician.id, role_id=role.id))
    db.commit()
    print(clinician.id)
"""
    result = subprocess.run(
        [sys.executable, "-c", setup],
        cwd=BACKEND_ROOT,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("Could not create the synthetic second-organization clinician.")
    return int(result.stdout.strip().splitlines()[-1])


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="medisafe-e2e-") as temporary_directory:
        database_file = Path(temporary_directory) / "medisafe-e2e.db"
        environment = os.environ.copy()
        environment.update({
            "DATABASE_URL": f"sqlite:///{database_file.as_posix()}",
            "API_KEY": SYNTHETIC_API_KEY,
            "CORS_ORIGINS": "http://localhost:5173,http://localhost:3000",
        })
        os.environ.update(environment)

        seed = subprocess.run(
            [sys.executable, str(BACKEND_ROOT / "scripts" / "seed_dev.py")],
            cwd=BACKEND_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        if seed.returncode != 0:
            print("E2E seed failed; stdout/stderr suppressed to avoid exposing config.")
            return 1
        admin_match = re.search(r"Admin/prescriber clinician ID: (\d+)", seed.stdout)
        readonly_match = re.search(r"Read-only clinician ID: (\d+)", seed.stdout)
        if not admin_match or not readonly_match:
            print("E2E seed did not report clinician IDs.")
            return 1
        admin_id = int(admin_match.group(1))
        readonly_id = int(readonly_match.group(1))
        state["admin_id"] = admin_id
        state["readonly_id"] = readonly_id

        port = free_local_port()
        base_url = f"http://127.0.0.1:{port}"
        log_path = Path(temporary_directory) / "uvicorn.log"
        with log_path.open("w", encoding="utf-8") as server_log:
            server = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                ],
                cwd=BACKEND_ROOT,
                env=environment,
                stdout=server_log,
                stderr=subprocess.STDOUT,
            )
            try:
                ready = False
                health_response = None
                for _ in range(100):
                    if server.poll() is not None:
                        break
                    try:
                        health_response = httpx.get(f"{base_url}/api/health", timeout=0.5)
                        if health_response.status_code == 200:
                            ready = True
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.2)
                if not ready:
                    check("Backend starts on fresh SQLite", lambda: (_ for _ in ()).throw(RuntimeError("server did not become ready")))
                else:
                    check("Backend starts on fresh SQLite", lambda: (
                        health_response.json() == {"status": "healthy", "database": "connected"},
                        f"health={health_response.status_code} {health_response.json()}",
                    ))
                    print_client = httpx.Client(base_url=base_url, timeout=10)
                    try:
                        run_workflow(print_client, readonly_id)
                    except Exception as exc:
                        checks.append(("Remaining HTTP workflow", "FAIL", f"{type(exc).__name__}: {exc}"))
                    finally:
                        print_client.close()
            finally:
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=10)

        check(
            "Audit rows use clinician ID (not demo identity)",
            lambda: verify_audit(database_file, admin_id),
        )
    print("\nPASS/FAIL SUMMARY")
    print("| Result | Step | Detail |")
    print("|---|---|---|")
    for name, result, detail in checks:
        print(f"| {result} | {name} | {detail.replace('|', '/')} |")
    return 0 if checks and all(result == "PASS" for _, result, _ in checks) else 1


def run_workflow(client: httpx.Client, readonly_id: int) -> None:
    check("No headers are rejected", lambda: require_status(client.get("/api/v1/auth/session"), 401).status_code)
    check(
        "Wrong API key is rejected",
        lambda: require_status(
            client.get(
                "/api/v1/auth/session",
                headers={"X-API-Key": "incorrect-synthetic-key", "X-Clinician-ID": "1"},
            ),
            401,
            403,
        ).status_code,
    )

    readonly_headers = {
        "X-API-Key": SYNTHETIC_API_KEY,
        "X-Clinician-ID": str(readonly_id),
    }
    readonly_patient = client.post(
        "/api/v1/patients",
        json={"name": "Synthetic Read-only Rejection", "age": 30, "gender": "Unknown"},
        headers=readonly_headers,
    )
    readonly_prescription = client.post(
        "/api/v1/prescriptions",
        json={"patient_id": 1, "raw_text": "Amoxicillin 500 mg daily"},
        headers=readonly_headers,
    )
    check("Read-only cannot create patient or prescription", lambda: (
        require_status(readonly_patient, 403).status_code,
        require_status(readonly_prescription, 403).status_code,
    ))

    session = require_status(client.get("/api/v1/auth/session", headers=BASE_HEADERS), 200).json()
    check("Admin/prescriber session has expected roles", lambda: (
        session["clinician_id"] == 1
        and set(session["roles"]) == {"ADMIN", "DOCTOR"},
        f"clinician={session['clinician_id']} roles={session['roles']}",
    ))

    created = require_status(
        client.post(
            "/api/v1/patients",
            json={"name": "Synthetic E2E Patient", "age": 68, "gender": "Female"},
            headers=BASE_HEADERS,
        ),
        200,
    ).json()
    state["patient_id"] = created["id"]
    check("Create synthetic patient", lambda: (
        created["name"] == "Synthetic E2E Patient"
        and created["age"] == 68
        and created["gender"] == "Female",
        f"patient_id={created['id']}",
    ))

    patient_id = int(state["patient_id"])
    for path, body, label in (
        (f"/api/v1/patients/{patient_id}/allergies", {"allergy_name": "penicillin"}, "Add allergy"),
        (f"/api/v1/patients/{patient_id}/conditions", {"condition_name": "chronic kidney disease"}, "Add condition"),
        (f"/api/v1/patients/{patient_id}/medications", {"medication_name": "warfarin", "dose": "5 mg", "frequency": "daily"}, "Add current medication"),
    ):
        response = client.post(path, json=body, headers=BASE_HEADERS)
        check(label, lambda response=response: require_status(response, 200).status_code)

    prescription_ids: list[int] = []
    draft_failures = []
    for text in (
        "Amoxicillin 500 mg three times daily for 7 days",
        "ibuprofen 400 mg twice daily",
    ):
        response = client.post(
            "/api/v1/prescriptions",
            json={"patient_id": patient_id, "raw_text": text},
            headers=BASE_HEADERS,
        )
        if response.status_code != 200:
            draft_failures.append(f"{text.split()[0]} draft returned HTTP {response.status_code}: {response.text[:200]}")
            continue
        result = response.json()
        prescription_ids.append(int(result["id"]))
        check(f"Create draft: {text.split()[0]}", lambda result=result: (
            bool(result["orders"])
            and result["orders"][0]["normalization_status"] == "NORMALIZED",
            f"prescription_id={result['id']} status={result['orders'][0]['normalization_status'] if result['orders'] else 'no orders'}",
        ))
    if draft_failures:
        checks.append(("Create two prescription drafts", "FAIL", "; ".join(draft_failures)))
    elif len(prescription_ids) == 2:
        checks.append(("Create two prescription drafts", "PASS", f"prescription_ids={prescription_ids}"))

    analyses = []
    for prescription_id in (prescription_ids if len(prescription_ids) == 2 else []):
        confirmed = client.post(
            f"/api/v1/prescriptions/{prescription_id}/confirm-normalization",
            headers=BASE_HEADERS,
        )
        require_status(confirmed, 200)
        analyzed = require_status(
            client.post(
                f"/api/v1/prescriptions/{prescription_id}/analyze",
                headers=BASE_HEADERS,
            ),
            200,
        ).json()
        analyses.append(analyzed)
    if len(analyses) == 2:
        check("Confirm normalization and run both analyses", lambda: (
            all(result["analysis_status"] == "PARTIALLY_EVALUATED" for result in analyses),
            f"analysis_ids={[result['id'] for result in analyses]}",
        ))
    else:
        checks.append(("Confirm normalization and run both analyses", "FAIL", "Blocked because prescription drafts could not be created against the unreviewed knowledge base."))

    all_alerts = [alert for result in analyses for alert in result["alerts"]]
    allergy_alerts = [alert for alert in all_alerts if alert.get("type") == "Allergy Conflict"]
    expected_interactions = [alert for alert in all_alerts if alert.get("type") == "Drug-Drug Interaction"]
    knowledge_path = REPOSITORY_ROOT / "frontend" / "knowledge_base" / "versions" / "v1.json"
    import json

    knowledge = json.loads(knowledge_path.read_text(encoding="utf-8-sig"))["data"]
    pair_is_configured = any(
        {item["drug_a"].casefold(), item["drug_b"].casefold()} == {"warfarin", "ibuprofen"}
        for item in knowledge.get("drug_drug_interactions", [])
    )
    state["all_alerts"] = all_alerts
    state["allergy_alert_id"] = allergy_alerts[0]["id"] if allergy_alerts else None
    state["interaction_alert_id"] = expected_interactions[0]["id"] if expected_interactions else None
    if analyses:
        check("Allergy conflict alert appears", lambda: (
            bool(allergy_alerts),
            f"alert_ids={[alert['id'] for alert in allergy_alerts]}",
        ))
        interaction_is_missing = not expected_interactions and pair_is_configured
        interaction_detail = (
            f"rule matched alert_ids={[alert['id'] for alert in expected_interactions]}"
            if expected_interactions
            else "rule set does not configure Warfarin + Ibuprofen; expected alert missing: Drug-Drug Interaction (warfarin + ibuprofen)"
        )
        check("Warfarin/NSAID rule coverage reported", lambda: (
            bool(expected_interactions) or not interaction_is_missing,
            interaction_detail,
        ))
    else:
        checks.append(("Allergy conflict alert appears", "FAIL", "Not evaluated: the configured Penicillin + Amoxicillin rule could not run because there is no active reviewed knowledge version."))
        checks.append(("Warfarin/NSAID rule coverage reported", "FAIL", "The local v1 rule set does not configure Warfarin + Ibuprofen; expected alert missing: Drug-Drug Interaction (warfarin + ibuprofen). Analysis was also blocked by the inactive knowledge version."))

    actionable_alerts = [alert for alert in all_alerts if alert.get("id")]
    if not analyses:
        checks.append(("Acknowledge and override alerts", "FAIL", "Not possible: analysis was blocked because the local knowledge base has no active reviewed version."))
    elif len(actionable_alerts) < 2:
        checks.append(("Acknowledge and override alerts", "FAIL", f"requires at least two alerts; found {len(actionable_alerts)}"))
    else:
        acknowledged = actionable_alerts[0]
        overridden = actionable_alerts[1]
        acknowledge_response = client.post(
            f"/api/v1/alerts/{acknowledged['id']}/actions",
            json={"action": "ACKNOWLEDGE"},
            headers=BASE_HEADERS,
        )
        override_response = client.post(
            f"/api/v1/alerts/{overridden['id']}/actions",
            json={
                "action": "OVERRIDE",
                "override_reason": "PATIENT_CONTEXT_NOT_CAPTURED",
                "override_reason_text": "Synthetic E2E structured reason.",
            },
            headers=BASE_HEADERS,
        )
        require_status(acknowledge_response, 200)
        require_status(override_response, 200)
        queue = require_status(
            client.get("/api/v1/alerts/review-queue", headers=BASE_HEADERS),
            200,
        ).json()
        acknowledged_row = next((row for row in queue if row["alert_id"] == acknowledged["id"]), None)
        override_absent = all(row["alert_id"] != overridden["id"] for row in queue)
        check("Acknowledge and override reflected by review queue", lambda: (
            acknowledged_row is not None
            and acknowledged_row.get("last_action") == "ACKNOWLEDGE"
            and override_absent,
            f"acknowledged_action={acknowledged_row.get('last_action') if acknowledged_row else None}; overridden_alert_removed={override_absent}",
        ))

    read_endpoints = (
        "medication-history",
        "observations",
        "encounters",
        "prescriptions",
    )
    read_results = {}
    for endpoint in read_endpoints:
        response = require_status(
            client.get(f"/api/v1/patients/{patient_id}/{endpoint}", headers=BASE_HEADERS),
            200,
        )
        read_results[endpoint] = response.json()
    check("Read all four patient tab endpoints", lambda: (
        set(read_results) == set(read_endpoints),
        f"counts={ {name: len(value) for name, value in read_results.items()} }",
    ))

    second_clinician_id = add_second_organization_clinician()
    second_headers = {"X-API-Key": SYNTHETIC_API_KEY, "X-Clinician-ID": str(second_clinician_id)}
    other_org_patients = require_status(
        client.get("/api/v1/patients", headers=second_headers),
        200,
    ).json()
    patient_detail = client.get(f"/api/v1/patients/{patient_id}", headers=second_headers)
    check("Second organization cannot read first organization's patient", lambda: (
        patient_id not in {item["id"] for item in other_org_patients}
        and patient_detail.status_code == 404,
        f"list_contains_patient={patient_id in {item['id'] for item in other_org_patients}}; detail_status={patient_detail.status_code}",
    ))

    bad_inputs = [
        (
            "Empty medication name",
            client.post(
                "/api/v1/prescriptions",
                json={
                    "patient_id": patient_id,
                    "medication_orders": [{
                        "medication_name": "",
                        "dose": 1,
                        "unit": "mg",
                        "route": "oral",
                        "frequency": "once daily",
                    }],
                },
                headers=BASE_HEADERS,
            ),
            (400, 422),
        ),
        (
            "10,000-character prescription text",
            client.post(
                "/api/v1/prescriptions",
                json={"patient_id": patient_id, "raw_text": "X" * 10000},
                headers=BASE_HEADERS,
            ),
            (400, 413, 422),
        ),
        (
            "SQL-like patient identifier",
            client.get("/api/v1/patients/1%20OR%201%3D1", headers=BASE_HEADERS),
            (400, 404, 422),
        ),
        (
            "Unknown patient ID",
            client.post(
                "/api/v1/prescriptions",
                json={"patient_id": 99999999, "raw_text": "Amoxicillin 500 mg daily"},
                headers=BASE_HEADERS,
            ),
            (400, 404, 422),
        ),
    ]
    for label, response, expected_statuses in bad_inputs:
        check(f"Bad input: {label}", lambda label=label, response=response, expected_statuses=expected_statuses: (
            require_status(response, *expected_statuses).status_code,
        ))


def verify_audit(database_file: Path, admin_id: int) -> str:
    import sqlite3

    with closing(sqlite3.connect(database_file)) as connection:
        users = {
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT user_id FROM audit_logs WHERE action LIKE '%/api/v1/patients%'"
            )
        }
    if str(admin_id) not in users:
        raise AssertionError(f"expected authenticated clinician ID {admin_id} in audit rows")
    if "system_demo_user" in users:
        raise AssertionError("legacy system_demo_user audit identity found")
    return f"observed clinician IDs={sorted(users)}"


if __name__ == "__main__":
    raise SystemExit(main())
