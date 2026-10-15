"""Test self-improvement endpoints directly"""
import os
from pathlib import Path
os.environ["DATABASE_URL"] = "sqlite://"
os.environ.setdefault("API_KEY", "synthetic-developer-test-key")

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.core.database import Base, get_db
from main import app
from fastapi.testclient import TestClient
from app.models.clinical import Organization, Role, User, UserRole

# Use in-memory SQLite for tests
SQLALCHEMY_DATABASE_URL = "sqlite://"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Override get_db
def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        pass

app.dependency_overrides[get_db] = override_get_db

# Create tables
Base.metadata.create_all(bind=engine)

with TestingSessionLocal() as db:
    org = Organization(id=1, name="Synthetic Developer Test Organization")
    role = Role(name="DOCTOR")
    user = User(organization_id=1, email="synthetic-doctor@tests.invalid", email_normalized="synthetic-doctor@tests.invalid", display_name="Synthetic Developer Test Doctor")
    db.add_all([org, role, user])
    db.flush()
    db.add(UserRole(user_id=user.id, role_id=role.id))
    db.commit()
    CLINICIAN_ID = user.id

TEST_HEADERS = {"X-API-Key": os.environ["API_KEY"], "X-Clinician-ID": str(CLINICIAN_ID)}

client = TestClient(app)

print("=== 1. Create patient ===")
r = client.post("/api/v1/patients", json={"name": "Synthetic Developer Test Patient", "age": 65, "gender": "Male"}, headers=TEST_HEADERS)
print(f"Status: {r.status_code}")
print(r.json())
pid = r.json()["id"]

print("\n=== 2. Add allergy ===")
r = client.post(f"/api/v1/patients/{pid}/allergies", json={"allergy_name": "Penicillin"}, headers=TEST_HEADERS)
print(f"Status: {r.status_code}")
print(r.json())

print("\n=== 3. Analyze ===")
r = client.post("/api/v1/prescriptions/analyze",
    json={"patient_id": pid, "raw_text": "Start amoxicillin 500mg twice daily for 7 days", "items": []},
    headers=TEST_HEADERS)
print(f"Status: {r.status_code}")
data = r.json()
print(f"Score={data['score']} Level={data['risk_level']} Alerts={data['total_alerts']} ID={data['id']}")
for a in data['alerts']:
    print(f"  [{a['severity']}] {a['type']}")
aid = data['id']

print("\n=== 4. Submit 3 feedback entries ===")
for i in range(3):
    r = client.post(f"/api/v1/prescriptions/analyze/{aid}/feedback",
        json={"alert_index": 1, "override_decision": False, "clinician_note": "Dosage alert is noisy", "alert_type": "Dosage Verification", "drug_name": "Amoxicillin"},
        headers=TEST_HEADERS)
    print(f"Feedback {i+1}: status={r.status_code} {r.json()}")

print("\n=== 5. Feedback analytics ===")
r = client.get("/api/v1/feedback/analytics", headers=TEST_HEADERS)
print(f"Status: {r.status_code}")
if r.status_code == 200:
    data = r.json()
    print(f"Total: {data['total_feedback']}")
    print(f"Agreement: {data['agreement_rate']*100:.0f}%  Disagreement: {data['disagreement_rate']*100:.0f}%")
    print(f"Adapted: {data['adapted_types']}")
    for t, s in data['per_type_stats'].items():
        print(f"  {t}: n={s['total']} agree={s['agreed']} disagree={s['disagreed']} rate={s['disagreement_rate']} factor={s['adjustment_factor']} adapted={s['adapted']}")
else:
    print(f"ERROR: {r.text}")

print("\n=== 6. Re-evaluate ===")
r = client.post(f"/api/v1/prescriptions/analyze/{aid}/reevaluate", headers=TEST_HEADERS)
print(f"Status: {r.status_code}")
if r.status_code == 200:
    data = r.json()
    print(f"Score={data['score']} Level={data['risk_level']} Adapted={data['feedback_adapted']} Types={data['adapted_types']}")
    for b in data['score_breakdown']:
        adj = ' **ADJUSTED**' if b.get('adjusted') else ''
        print(f"  {b['alert_type']}: {b['points_original']} -> {b['points_added']} pts (sev={b['severity']}){adj}")
else:
    print(f"ERROR: {r.text}")

print("\n=== DONE ===")
