API_KEY_HEADERS = {"X-API-Key": "synthetic-test-api-key", "X-Clinician-ID": "2"}


def _create_patient(client, *, age: int):
    response = client.post(
        "/api/v1/patients",
        json={"name": "Synthetic Scenario Patient", "age": age, "gender": "Male"},
        headers={**API_KEY_HEADERS, "X-Clinician-ID": "2"},
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_happy_path_demo(client):
    patient_id = _create_patient(client, age=45)
    response = client.post(
        "/api/v1/prescriptions/analyze",
        json={
            "patient_id": patient_id,
            "raw_text": "Take paracetamol 500mg twice daily for 3 days.",
            "items": [],
        },
        headers=API_KEY_HEADERS,
    )

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["score"] == 0
    assert result["risk_level"] == "Low"
    assert result["total_alerts"] == 0
    assert result["alerts"] == []


def test_pathological_path_demo(client, monkeypatch):
    patient_id = _create_patient(client, age=65)
    assert client.post(
        f"/api/v1/patients/{patient_id}/allergies",
        json={"allergy_name": "Penicillin"},
        headers={**API_KEY_HEADERS, "X-Clinician-ID": "2"},
    ).status_code == 200
    assert client.post(
        f"/api/v1/patients/{patient_id}/conditions",
        json={"condition_name": "Hypertension"},
        headers={**API_KEY_HEADERS, "X-Clinician-ID": "2"},
    ).status_code == 200
    assert client.post(
        f"/api/v1/patients/{patient_id}/medications",
        json={"medication_name": "Warfarin", "dose": "5mg", "frequency": "Daily"},
        headers={**API_KEY_HEADERS, "X-Clinician-ID": "2"},
    ).status_code == 200

    response = client.post(
        "/api/v1/prescriptions/analyze",
        json={
            "patient_id": patient_id,
            "raw_text": (
                "Start amoxicillin 500mg twice daily. Also add ibuprofen 400mg "
                "as needed for pain, and paracetamol 5000mg once daily."
            ),
            "items": [],
        },
        headers=API_KEY_HEADERS,
    )

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["score"] > 60
    assert result["risk_level"] in {"High", "Critical"}
    alert_severities = {(alert["type"], alert["severity"]) for alert in result["alerts"]}
    assert ("Allergy Conflict", "CRITICAL") in alert_severities
    assert ("Drug-Disease Interaction", "HIGH") in alert_severities
    assert ("Dosage Error", "HIGH") in alert_severities
    assert ("Dosage Verification", "INFORMATIONAL") in alert_severities
    assert [alert["type"] for alert in result["alerts"][:3]] == [
        "Allergy Conflict",
        "Drug-Disease Interaction",
        "Dosage Error",
    ]
    assert all(alert["severity"] == "INFORMATIONAL" for alert in result["alerts"][3:])

