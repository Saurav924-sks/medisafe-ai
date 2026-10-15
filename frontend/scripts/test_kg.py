import sys
import os

# Add the backend folder to the path so we can import app modules
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'backend'))

from app.services.knowledge_graph import med_kg

def test_knowledge_graph():
    print("🧪 Testing Medication Knowledge Graph...\n")

    # Test 1: Drug Info
    print("1. Drug Info Lookup:")
    info = med_kg.get_drug_info("Warfarin")
    print(f"   Warfarin Class: {info.get('class')}")

    # Test 2: Drug-Drug Interaction
    print("\n2. Drug-Drug Interaction (Warfarin + Aspirin):")
    interaction = med_kg.check_interaction("Warfarin", "Aspirin")
    if interaction:
        print(f"   ✅ DETECTED: Severity {interaction['severity']}")
        print(f"   Reason: {interaction['reason']}")
    else:
        print("   ❌ No interaction found.")

    # Test 3: Drug-Disease Contraindication
    print("\n3. Drug-Disease Contraindication (Ibuprofen + Hypertension):")
    contraindication = med_kg.check_disease_contraindication("Ibuprofen", "Hypertension")
    if contraindication:
        print(f"   ✅ DETECTED: Severity {contraindication['severity']}")
        print(f"   Reason: {contraindication['reason']}")

    # Test 4: Allergy Trigger
    print("\n4. Allergy Trigger (Penicillin allergy + Amoxicillin prescription):")
    allergy = med_kg.check_allergy_trigger("Penicillin", "Amoxicillin")
    if allergy:
        print(f"   ✅ DETECTED: Severity {allergy['severity']}")
        print(f"   Reason: {allergy['reason']}")

    print("\n✅ Knowledge Graph tests completed successfully!")

if __name__ == "__main__":
    test_knowledge_graph()
