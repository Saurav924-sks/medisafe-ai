import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'backend'))

from app.services.rxnorm_service import get_rxcui_by_name
from app.services.openfda_service import get_drug_interactions
from app.services.knowledge_graph import med_kg


def test_real_world_data():
    print("🧪 Testing RxNorm and openFDA Data Integration...\n")

    # Test 1: RxNorm Normalization
    print("1. RxNorm Normalization:")
    rxcui = get_rxcui_by_name("Lipitor")
    print(f"   'Lipitor' normalized to RXCUI: {rxcui}")

    # Test 2: openFDA Interactions
    print("\n2. openFDA Interactions for Warfarin (RXCUI 11289):")
    interactions = get_drug_interactions("11289")
    if interactions:
        print(f"   ✅ Found {len(interactions)} FDA label interaction sections.")
        description = interactions[0]["description"]
        print(f"   Example label text: {description[:240]}...")
    else:
        print("   ❌ No label sections found or the API is unavailable.")

    # Test 3: Hybrid Knowledge Graph
    print("\n3. Hybrid Knowledge Graph Check (Warfarin + Aspirin):")
    # The local JSON graph is checked first; the API may provide a fallback.
    result = med_kg.check_interaction("Warfarin", "Aspirin")
    if result:
        print(f"   ✅ DETECTED via {result.get('source', 'Local JSON')}")
        print(f"   Reason: {result['reason']}")
    else:
        print("   ❌ Interaction not detected.")

    print("\n4. openFDA Label Fallback (Warfarin + Ibuprofen):")
    fallback = med_kg.check_interaction("Warfarin", "Ibuprofen")
    if fallback:
        print(f"   ✅ Label mention found via {fallback['source']}")
        print(f"   Evidence: {fallback['evidence']}")
    else:
        print("   ❌ No matching label mention found or external API unavailable.")

    print("\nNote: FDA label mentions are unstructured and are not verified pairwise interactions.")
    print("✅ External API integration smoke test completed!")


if __name__ == "__main__":
    test_real_world_data()
