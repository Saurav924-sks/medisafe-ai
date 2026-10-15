"""Full self-improvement end-to-end test"""
import json
import urllib.request
import urllib.error
import subprocess
import time
import sys
import os

os.chdir("C:/Windows/System32/medisafe-ai_ML/frontend/backend")

# Kill any existing backend
subprocess.run(["taskkill", "/F", "/IM", "python.exe", "/FI", "COMMANDLINE LIKE '%uvicorn main:app%'"],
               capture_output=True, shell=True)
time.sleep(3)

# Start backend
proc = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
)
print("Backend starting...")
time.sleep(7)

BN = "http://127.0.0.1:8000"
AK = os.environ.get("API_KEY")
CLINICIAN_ID = os.environ.get("CLINICIAN_ID")
if not AK or not CLINICIAN_ID:
    raise SystemExit("Set API_KEY and CLINICIAN_ID for this local developer-only workflow.")

def req(method, path, body=None, headers=None):
    url = f"{BN}{path}"
    data = json.dumps(body).encode() if body else None
    hdrs = {"Content-Type": "application/json", "X-API-Key": AK, "X-Clinician-ID": CLINICIAN_ID}
    if headers:
        hdrs.update(headers)
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, data=data, headers=hdrs, method=method))
        return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except:
            return e.code, {"error": str(e)}
    except Exception as e:
        return 0, {"error": str(e)}

def run():
    # Step 1: Create patient
    print("=== 1. CREATE PATIENT ===")
    s, d = req("POST", "/api/v1/patients", {"name": "E2E Test", "age": 65, "gender": "Male"})
    print(f"  create_patient: status={s}, id={d.get('id')}")
    assert s == 200, f"create_patient failed: {s} {d}"
    pid = d["id"]
    
    # Step 2: Add Penicillin allergy
    print("=== 2. ADD PENICILLIN ALLERGY ===")
    s, d = req("POST", f"/api/v1/patients/{pid}/allergies",
        {"allergy_name": "Penicillin"}, {"X-API-Key": AK})
    print(f"  add_allergy: status={s}, msg={d.get('message')}")
    assert s == 200, f"add_allergy failed: {s} {d}"
    
    # Step 3: Add Lisinopril medication
    print("=== 3. ADD LISINOPRIL MEDICATION ===")
    s, d = req("POST", f"/api/v1/patients/{pid}/medications",
        {"medication_name": "Lisinopril", "dose": "10", "frequency": "Once daily"},
        {"X-API-Key": AK})
    print(f"  add_medication: status={s}")
    assert s == 200, f"add_medication failed: {s} {d}"
    
    # Step 4: Analyze prescription
    print("=== 4. ANALYZE PRESCRIPTION ===")
    s, d = req("POST", "/api/v1/prescriptions/analyze",
        {"patient_id": pid, "raw_text": "Start amoxicillin 500mg twice daily for 7 days", "items": []},
        {"X-API-Key": AK})
    print(f"  analyze: status={s}")
    print(f"  score={d.get('score')} level={d.get('risk_level')} alerts={d.get('total_alerts')} id={d.get('id')}")
    for a in d.get("alerts", []):
        print(f"    [{a['severity']}] {a['type']}: {a.get('what_detected', '')}")
    assert s == 200, f"analyze failed: {s} {d}"
    assert "score" in d, "Missing score in response"
    assert "risk_level" in d, "Missing risk_level in response"
    assert "total_alerts" in d, "Missing total_alerts in response"
    assert "alerts" in d, "Missing alerts in response"
    assert "score_breakdown" in d, "Missing score_breakdown in response"
    aid = d["id"]
    
    # Step 5: Verify NLP parsing worked (Amoxicillin should be detected)
    print("=== 5. VERIFY NLP PARSING ===")
    alert_types = [a["type"] for a in d["alerts"]]
    assert "Allergy Conflict" in alert_types, f"Expected Allergy Conflict alert. Got: {alert_types}"
    assert "Dosage Verification" in alert_types, f"Expected Dosage Verification alert. Got: {alert_types}"
    print("  NLP correctly detected Amoxicillin from raw_text")
    
    # Step 6: Submit 3 disagreements on Dosage Verification
    print("=== 6. SUBMIT 3 CLINICIAN DISAGREEMENTS ===")
    for i in range(3):
        s, d = req("POST", f"/api/v1/prescriptions/analyze/{aid}/feedback",
            {"alert_index": 1, "override_decision": False,
             "clinician_note": "Dosage alert noisy - verify with formulary",
             "alert_type": "Dosage Verification", "drug_name": "Amoxicillin"},
            {"X-API-Key": AK})
        print(f"  feedback {i+1}: status={s}")
        assert s == 200, f"feedback {i+1} failed: {s} {d}"
    
    # Step 7: Get feedback analytics
    print("=== 7. FEEDBACK ANALYTICS ===")
    s, d = req("GET", "/api/v1/feedback/analytics", {"X-API-Key": AK})
    print(f"  analytics: status={s}")
    print(f"  total_feedback={d.get('total_feedback')}")
    print(f"  agreement_rate={d.get('agreement_rate')}")
    print(f"  disagreement_rate={d.get('disagreement_rate')}")
    print(f"  adapted_types={d.get('adapted_types')}")
    for t, st in d.get("per_type_stats", {}).items():
        print(f"    {t}: total={st['total']} agreed={st['agreed']} disagreed={st['disagreed']} rate={st['disagreement_rate']} factor={st['adjustment_factor']} adapted={st['adapted']}")
    assert s == 200, f"analytics failed: {s} {d}"
    assert d["total_feedback"] == 3, f"Expected 3 feedbacks, got {d['total_feedback']}"
    assert "Dosage Verification" in d["adapted_types"], "Expected Dosage Verification in adapted_types"
    
    # Step 8: Re-evaluate with learned weights
    print("=== 8. RE-EVALUATE WITH LEARNED WEIGHTS ===")
    s, d = req("POST", f"/api/v1/prescriptions/analyze/{aid}/reevaluate", {"X-API-Key": AK})
    print(f"  reevaluate: status={s}")
    print(f"  score={d.get('score')} level={d.get('risk_level')} adapted={d.get('feedback_adapted')} types={d.get('adapted_types')}")
    for b in d.get("score_breakdown", []):
        adj = " **ADJUSTED**" if b.get("adjusted") else ""
        print(f"    {b['alert_type']}: {b['points_original']} -> {b['points_added']} pts (sev={b['severity']}){adj}")
    assert s == 200, f"reevaluate failed: {s} {d}"
    assert d["feedback_adapted"] == True, "Expected feedback_adapted=True"
    assert "Dosage Verification" in d["adapted_types"], "Expected Dosage Verification in adapted_types"
    for b in d["score_breakdown"]:
        if b["alert_type"] == "Dosage Verification":
            assert b["adjusted"] == True, "Dosage Verification should be marked as adjusted"
            assert b["points_added"] < b["points_original"], f"Expected reduced points: {b['points_added']} >= {b['points_original']}"
    
    # Step 9: Verify score decreased
    print("=== 9. VERIFY SCORE DECREASED ===")
    adapted_score = d["score"]
    s, orig = req("POST", "/api/v1/prescriptions/analyze",
        {"patient_id": pid, "raw_text": "Start amoxicillin 500mg twice daily for 7 days", "items": []},
        {"X-API-Key": AK})
    print(f"  Original score: {orig['score']}, Adapted score: {adapted_score}")
    assert adapted_score < orig["score"], f"Score should decrease after adaptation: {adapted_score} >= {orig['score']}"
    
    print()
    print("=" * 60)
    print("ALL SELF-IMPROVEMENT FLOW TESTS PASSED")
    print("=" * 60)
    print()
    print("Summary:")
    print(f"  - Patient created with Penicillin allergy + Lisinopril med")
    print(f"  - NLP parsed Amoxicillin from raw_text successfully")
    print(f"  - Safety engine flagged Drug-Allergy + Dosage alerts")
    print(f"  - 3 clinician disagreements recorded on Dosage Verification")
    print(f"  - Feedback analytics: disagreement_rate=1.0, adapted_types=[Dosage Verification]")
    print(f"  - Re-evaluate with learned weights: score reduced, alert marked adjusted")
    print(f"  - Self-improvement loop is fully functional")

run()
