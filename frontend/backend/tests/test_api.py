def test_create_patient(client):
    """Test creating a patient via the API."""
    response = client.post("/api/v1/patients", json={
        "name": "Test Patient",
        "age": 40,
        "gender": "Female"
    }, headers={"X-API-Key": "synthetic-test-api-key", "X-Clinician-ID": "2"})
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Test Patient"
    assert "id" in data


def test_authenticated_session_exposes_backend_roles(client):
    response = client.get("/api/v1/auth/session", headers={"X-API-Key": "synthetic-test-api-key", "X-Clinician-ID": "2"})
    assert response.status_code == 200, response.text
    assert response.json()["roles"] == ["DOCTOR"]

def test_analyze_prescription_missing_api_key(client):
    """Test that the API rejects requests without the API key."""
    response = client.post("/api/v1/prescriptions/analyze", json={
        "patient_id": 999, # Doesn't matter, should fail auth first
        "raw_text": "test",
        "items": []
    })
    assert response.status_code == 401

def test_analyze_prescription_success(client):
    """Test the full analysis pipeline via API."""
    # 1. Create a patient
    patient_res = client.post("/api/v1/patients", json={"name": "Synthetic Jane", "age": 30, "gender": "F"}, headers={"X-API-Key": "synthetic-test-api-key", "X-Clinician-ID": "2"})
    patient_id = patient_res.json()["id"]

    # 2. Add an allergy
    client.post(f"/api/v1/patients/{patient_id}/allergies", json={"allergy_name": "Penicillin"}, headers={"X-API-Key": "synthetic-test-api-key", "X-Clinician-ID": "2"})

    # 3. Run analysis with the correct API key
    response = client.post("/api/v1/prescriptions/analyze",
        json={
            "patient_id": patient_id,
            "raw_text": "Take amoxicillin 500mg daily",
            "items": []
        },
        headers={"X-API-Key": "synthetic-test-api-key", "X-Clinician-ID": "2"}
    )

    assert response.status_code == 200
    data = response.json()

    # Verify the structure of the response
    assert "score" in data
    assert "risk_level" in data
    assert "alerts" in data

    # Verify it caught the allergy
    allergy_alerts = [a for a in data["alerts"] if a["type"] == "Allergy Conflict"]
    assert len(allergy_alerts) > 0

