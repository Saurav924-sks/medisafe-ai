import sys
import os
import json
from pathlib import Path

# Add the backend folder to the path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'backend'))

from app.services.risk_scorer import calculate_risk_score

knowledge_path = Path(__file__).resolve().parents[1] / "knowledge_base" / "versions" / "v1.json"
priority_config = json.loads(knowledge_path.read_text(encoding="utf-8"))["data"]["priority_scoring"]

def test_risk_scorer():
    print("🧪 Testing Risk Scorer...\n")

    # Scenario 1: No alerts (Healthy prescription)
    print("--- Scenario 1: No Alerts ---")
    score_1 = calculate_risk_score([], priority_config)
    print(f"Score: {score_1['score']}/100 | Level: {score_1['risk_level']}")

    # Scenario 2: Moderate risk (One MODERATE alert)
    print("\n--- Scenario 2: One Moderate Alert ---")
    alerts_2 = [{"type": "Drug-Disease Interaction", "severity": "MODERATE", "drug": "Ibuprofen"}]
    score_2 = calculate_risk_score(alerts_2, priority_config)
    print(f"Score: {score_2['score']}/100 | Level: {score_2['risk_level']}")

    # Scenario 3: High/Critical risk (Multiple severe alerts)
    print("\n--- Scenario 3: Multiple Severe Alerts ---")
    alerts_3 = [
        {"type": "Allergy Conflict", "severity": "CRITICAL", "drug": "Amoxicillin"},
        {"type": "Drug-Drug Interaction", "severity": "HIGH", "drug_a": "Warfarin", "drug_b": "Aspirin"},
        {"type": "Dosage Error", "severity": "HIGH", "drug": "Paracetamol"}
    ]
    score_3 = calculate_risk_score(alerts_3, priority_config)
    print(f"Score: {score_3['score']}/100 | Level: {score_3['risk_level']}")
    
    # Show the breakdown to prove explainability
    print("\nScore Breakdown:")
    for item in score_3['score_breakdown']:
        print(f"  - {item['alert_type']} ({item['severity']}): +{item['points_added']} points")

    print("\n✅ Risk Scorer tests completed!")

if __name__ == "__main__":
    test_risk_scorer()
