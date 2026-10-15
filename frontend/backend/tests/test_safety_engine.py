from app.services.safety_engine import safety_engine

def test_allergy_conflict_detection():
    """Test that the engine catches a known allergy."""
    patient = {
        "allergies": [{"allergy_name": "Penicillin"}],
        "conditions": [],
        "current_medications": []
    }
    prescription = [{"drug_name": "Amoxicillin", "dose": "500", "unit": "mg"}]
    
    alerts = safety_engine.analyze(patient, prescription)
    
    # We expect exactly 1 alert (the allergy) plus 1 informational dosage fallback
    allergy_alerts = [a for a in alerts if a["type"] == "Allergy Conflict"]
    assert len(allergy_alerts) == 1
    assert allergy_alerts[0]["severity"] == "CRITICAL"
    assert allergy_alerts[0]["drug"] == "Amoxicillin"

def test_no_alerts_for_safe_prescription():
    """Test that a safe prescription doesn't trigger false positives."""
    patient = {
        "allergies": [],
        "conditions": [],
        "current_medications": []
    }
    # Paracetamol is safe here (no allergy, no disease, no current meds)
    prescription = [{"drug_name": "Paracetamol", "dose": "500", "unit": "mg"}]
    
    alerts = safety_engine.analyze(patient, prescription)
    
    # Should only have the informational dosage fallback, no real safety alerts
    real_alerts = [a for a in alerts if a["severity"] not in ["INFORMATIONAL"]]
    assert len(real_alerts) == 0

