import requests
from cachetools import TTLCache

# Cache to store API responses for 1 hour (3600 seconds) to avoid rate limits
rxnorm_cache = TTLCache(maxsize=1000, ttl=3600)

RXNORM_BASE_URL = "https://rxnav.nlm.nih.gov/REST"


def get_rxcui_by_name(drug_name: str) -> str | None:
    """
    Queries the NLM RxNorm API to get the standard RXCUI for a drug name.
    Returns the RXCUI string or None if not found.
    """
    drug_name_lower = drug_name.lower().strip()

    # Check cache first
    if drug_name_lower in rxnorm_cache:
        return rxnorm_cache[drug_name_lower]

    try:
        # Use the 'approximateTerm' endpoint for fuzzy matching.
        response = requests.get(
            f"{RXNORM_BASE_URL}/approximateTerm.json",
            params={"term": drug_name, "maxEntries": 1},
            timeout=5,
        )

        if response.status_code == 200:
            data = response.json()
            candidates = data.get("approximateGroup", {}).get("candidate", [])
            if candidates:
                rxcui = candidates[0].get("rxcui")
                rxnorm_cache[drug_name_lower] = rxcui
                return rxcui
    except (requests.RequestException, ValueError) as exc:
        print(f"RxNorm API Error: {exc}")

    rxnorm_cache[drug_name_lower] = None
    return None


def get_drug_properties(rxcui: str) -> dict:
    """Fetches drug properties (like brand names, ingredients) using RXCUI."""
    if not rxcui:
        return {}

    cache_key = f"properties_{rxcui}"
    if cache_key in rxnorm_cache:
        return rxnorm_cache[cache_key]

    try:
        response = requests.get(
            f"{RXNORM_BASE_URL}/rxcui/{rxcui}/properties.json",
            timeout=5,
        )
        if response.status_code == 200:
            properties = response.json().get("properties", {})
            rxnorm_cache[cache_key] = properties
            return properties
    except (requests.RequestException, ValueError) as exc:
        print(f"RxNorm Properties API Error: {exc}")

    rxnorm_cache[cache_key] = {}
    return {}
