import requests
from cachetools import TTLCache
from app.services.rxnorm_service import get_drug_properties

interaction_cache = TTLCache(maxsize=500, ttl=3600)

OPENFDA_BASE_URL = "https://api.fda.gov/drug/label.json"


def get_drug_interactions(rxcui: str) -> list:
    """
    Retrieves FDA drug-label interaction sections for an RxNorm concept.

    openFDA does not expose a `/drug/interaction.json` endpoint or a structured
    pairwise interaction database. Its drug-label endpoint supplies regulatory
    labeling text, which must not be treated as a verified pairwise interaction.
    """
    if not rxcui:
        return []

    cache_key = f"interactions_{rxcui}"
    if cache_key in interaction_cache:
        return interaction_cache[cache_key]

    try:
        rx_properties = get_drug_properties(rxcui)
        concept_name = rx_properties.get("name")
        if not concept_name:
            interaction_cache[cache_key] = []
            return []

        label_field = "brand_name" if rx_properties.get("tty") == "BN" else "generic_name"
        response = requests.get(
            OPENFDA_BASE_URL,
            params={"search": f"openfda.{label_field}:{concept_name}", "limit": 10},
            timeout=5,
        )

        if response.status_code == 200:
            data = response.json()
            results = data.get("results", [])

            interactions = []
            for result in results:
                interaction_text = result.get("drug_interactions", [])
                if interaction_text:
                    openfda = result.get("openfda", {})
                    interactions.append({
                        "drug_concept_name": (openfda.get("generic_name") or [concept_name])[0],
                        "interacting_drug": "Not specified by openFDA label data",
                        "severity": "INFORMATIONAL",
                        "description": " ".join(interaction_text),
                    })

            interaction_cache[cache_key] = interactions
            return interactions
    except (requests.RequestException, ValueError) as exc:
        print(f"openFDA API Error: {exc}")

    interaction_cache[cache_key] = []
    return []
