import sys
import os
import json

# Add the backend folder to the path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'backend'))

from app.services.safety_engine import safety_engine

def run_safety_engine_demo():
    print("🧪 Testing Medication Safety Engine...\n")

    # 1. Mock Patient Profile
    patient_profile = {
        "allergies": [{"allergy_name": "Penicillin"}],
        "conditions": [{"condition_name": "Hypertension"}],
        "current_medications": [{"medication_name": "Warfarin"}]
    }

    # 2. Mock New Prescription (Messy NLP output)
    # Contains: Amoxicillin (Allergy trigger), Ibuprofen (Disease conflict + Therapeutic duplicate if we had another NSAID),
    # and a massive dose of Paracetamol (Dosage error).
    new_prescription = [
        {"drug_name": "Amoxicillin", "dose": "500", "unit": "mg"},
        {"drug_name": "Ibuprofen", "dose": "400", "unit": "mg"},
        {"drug_name": "Paracetamol", "dose": "5000", "unit": "mg"} # Overdose! Max is 4000mg
    ]

    # 3. Run Analysis
    alerts = safety_engine.analyze(patient_profile, new_prescription)

    # 4. Print Results
    print(f"Total Alerts Generated: {len(alerts)}\n")
    print(json.dumps(alerts, indent=2))

    print("\n✅ Safety Engine tests completed!")

if __name__ == "__main__":
    run_safety_engine_demo()
