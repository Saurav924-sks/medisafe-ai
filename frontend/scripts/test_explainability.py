import sys
import os
import json

# Add the backend folder to the path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'backend'))

from app.services.explainability_engine import explainability_engine

def test_explainability():
    print("🧪 Testing Explainability Engine...\n")

    # Mock data from previous phases
    patient_profile = {
        "allergies": [{"allergy_name": "Penicillin"}],
        "conditions": [{"condition_name": "Hypertension"}],
        "current_medications": [{"medication_name": "Warfarin"}]
    }
    
    prescription = [
        {"drug_name": "Amoxicillin", "dose": "500", "unit": "mg"},
        {"drug_name": "Paracetamol", "dose": "5000", "unit": "mg"}
    ]

    # Mock raw alerts (simulating output from Safety Engine)
    raw_alerts = [
        {
            "type": "Allergy Conflict",
            "severity": "CRITICAL",
            "allergen": "Penicillin",
            "drug": "Amoxicillin",
            "reason": "Amoxicillin is a penicillin-class antibiotic. Patients with penicillin allergy are at high risk for anaphylaxis.",
            "evidence": "Standard Allergy Cross-Reactivity Guidelines.",
            "source": "Allergy Cross-Reactivity Database"
        },
        {
            "type": "Dosage Error",
            "severity": "HIGH",
            "drug": "Paracetamol",
            "prescribed_dose": "5000 mg",
            "max_safe_dose": "4000 mg",
            "reason": "Prescribed dose (5000 mg) exceeds the maximum recommended daily dose (4000 mg) for Paracetamol.",
            "evidence": "FDA Maximum Daily Dosage Guidelines",
            "source": "Drug Knowledge Graph"
        }
    ]

    # Run the engine
    explained_alerts = explainability_engine.generate_explanations(raw_alerts, patient_profile, prescription)

    # Print the first alert to show the 6-question structure
    print("--- Explained Alert 1 (Allergy) ---")
    alert1 = explained_alerts[0]
    print(f"1. What detected:      {alert1['what_detected']}")
    print(f"2. Involved entities:  {', '.join(alert1['involved_entities'])}")
    print(f"3. Why flagged:        {alert1['why_flagged']}")
    print(f"4. Trigger info:       {alert1['trigger_info']}")
    print(f"5. Evidence/Source:    {alert1['evidence']} ({alert1['source']})")
    print(f"6. Recommended action: {alert1['recommended_action']}")
    
    print("\n--- Explained Alert 2 (Dosage) ---")
    alert2 = explained_alerts[1]
    print(f"1. What detected:      {alert2['what_detected']}")
    print(f"2. Involved entities:  {', '.join(alert2['involved_entities'])}")
    print(f"3. Why flagged:        {alert2['why_flagged']}")
    print(f"4. Trigger info:       {alert2['trigger_info']}")
    print(f"5. Evidence/Source:    {alert2['evidence']} ({alert2['source']})")
    print(f"6. Recommended action: {alert2['recommended_action']}")

    print("\n✅ Explainability Engine tests completed!")

if __name__ == "__main__":
    test_explainability()
