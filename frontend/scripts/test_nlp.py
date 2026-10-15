import sys
import os

# Add the backend folder to the path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'backend'))

from app.services.nlp_parser import parse_prescription

def test_nlp_parser():
    print(" Testing NLP Prescription Parser...\n")

    test_cases = [
        "Take aspirin 100 mg twice daily for 5 days.",
        "Patient needs amoxicillin 500mg TDS for a week.",
        "Start warfarin 5mg once daily. Also add ibuprofen 400 mg as needed.",
        "Prescribe lisinopril 10mg daily."
    ]

    for i, text in enumerate(test_cases, 1):
        print(f"--- Test Case {i} ---")
        print(f"Input: \"{text}\"")
        results = parse_prescription(text)
        
        for item in results:
            if "error" in item:
                print(f"  ❌ Error: {item['error']}")
            else:
                print(f"  ✅ Drug: {item['drug_name']}")
                print(f"     Dose: {item['dose']} {item['unit']}")
                print(f"     Frequency: {item['frequency']}")
                print(f"     Duration: {item['duration']}")
        print()

    print("✅ NLP Parser tests completed!")

if __name__ == "__main__":
    test_nlp_parser()
