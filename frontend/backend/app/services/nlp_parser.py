import warnings
import spacy
import re
from thefuzz import fuzz, process
from app.services.knowledge_graph import med_kg

# Load the lightweight spaCy English model when available. Some local/dev
# environments do not have the model installed, so fall back to a minimal blank
# English pipeline instead of crashing the full service on import.
try:
    nlp = spacy.load("en_core_web_sm")
except OSError:
    warnings.warn(
        "en_core_web_sm not found; using spaCy blank English pipeline as a fallback.",
        RuntimeWarning,
        stacklevel=2,
    )
    nlp = spacy.blank("en")

# Common frequency mappings
FREQUENCY_MAP = {
    "once daily": "Once daily", "od": "Once daily", "daily": "Once daily",
    "twice daily": "Twice daily", "bd": "Twice daily", "bid": "Twice daily",
    "three times daily": "Three times daily", "tds": "Three times daily", "tid": "Three times daily",
    "four times daily": "Four times daily", "qid": "Four times daily",
    "every 8 hours": "Every 8 hours", "every 12 hours": "Every 12 hours",
    "as needed": "As needed", "prn": "As needed"
}

def extract_dose_and_unit(text: str):
    """Uses Regex to find doses like '500 mg', '100mg', '5 ml'."""
    # Regex looks for numbers (including decimals) followed by optional units
    pattern = r'(\d+(?:\.\d+)?)\s*(mg|mcg|g|ml|iu|units|tablet|capsule)?'
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        return match.group(1), match.group(2).upper() if match.group(2) else "Unknown"
    return None, None

def extract_frequency(text: str):
    """Finds frequency keywords in the text."""
    text_lower = text.lower()
    # Prefer specific phrases (for example, "twice daily" before "daily").
    for key, val in sorted(FREQUENCY_MAP.items(), key=lambda item: len(item[0]), reverse=True):
        if key in text_lower:
            return val
    return "Not specified"

def extract_duration(text: str):
    """Uses Regex to find durations like 'for 7 days', 'for 2 weeks'."""
    pattern = r'(?:for\s+)?(\d+(?:\.\d+)?)\s*(days?|weeks?|months?)'
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        return f"{match.group(1)} {match.group(2)}"
    return "Not specified"

def find_drugs_in_text(text: str, threshold: int = 80):
    """
    Uses Fuzzy Matching to find drug names from our Knowledge Graph in the text.
    This handles typos and case variations (e.g., 'aspirin' -> 'Aspirin').
    """
    # Get all nodes from the graph that are of type 'drug'
    known_drugs = [node for node, data in med_kg.graph.nodes(data=True) if data.get("type") == "drug"]
    
    found_drugs = []
    # We check each known drug to see if it appears in the text
    for drug in known_drugs:
        # Use partial ratio to handle cases where the drug is part of a longer sentence
        score = fuzz.partial_ratio(drug.lower(), text.lower())
        if score >= threshold:
            found_drugs.append({"canonical_name": drug, "match_score": score})
            
    # Sort by match score descending and remove duplicates
    found_drugs.sort(key=lambda x: x["match_score"], reverse=True)
    return [d["canonical_name"] for d in found_drugs]

def parse_prescription(raw_text: str):
    """
    Main function to parse a natural language prescription.
    Returns a list of structured prescription items.
    """
    # 1. Find all drugs mentioned in the text
    drugs = find_drugs_in_text(raw_text)
    
    if not drugs:
        return [{"error": "No recognized medications found in the text."}]

    # Locate each known drug mention and associate details only with the text
    # between it and the next drug mention. This avoids reusing the first dose
    # and frequency for every medication in a multi-drug prescription.
    mentions = []
    for drug_name in drugs:
        match = re.search(re.escape(drug_name), raw_text, re.IGNORECASE)
        if match:
            mentions.append((match.start(), match.end(), drug_name))

    mentions.sort(key=lambda mention: mention[0])
    if not mentions:
        # Preserve fuzzy-name matching behavior when the typed name is a typo.
        mentions = [(0, 0, drug_name) for drug_name in drugs]

    parsed_items = []
    for index, (start, end, drug_name) in enumerate(mentions):
        next_start = mentions[index + 1][0] if index + 1 < len(mentions) else len(raw_text)
        drug_text = raw_text[end:next_start] if end else raw_text
        dose, unit = extract_dose_and_unit(drug_text)
        frequency = extract_frequency(drug_text)
        duration = extract_duration(drug_text)

        # 3. Create a structured item for each found drug
        parsed_items.append({
            "drug_name": drug_name,
            "dose": dose,
            "unit": unit,
            "frequency": frequency,
            "duration": duration,
            "raw_text_snippet": raw_text # Keep original text for explainability
        })

    return parsed_items


def parse_prescription_draft(raw_text: str, knowledge_data: dict | None = None) -> dict:
    """Extract only exact local drug-name mentions into an unconfirmed draft.

    This path deliberately does not use fuzzy best-match selection. Missing drug
    names route the caller to manual structured entry instead of being guessed.
    """
    if not raw_text or not raw_text.strip():
        return {"status": "MANUAL_ENTRY_REQUIRED", "orders": []}

    known_drugs = (
        list(knowledge_data.get("drugs", {})) if knowledge_data is not None else [
            node for node, data in med_kg.graph.nodes(data=True) if data.get("type") == "drug"
        ]
    )
    matches = []
    for drug_name in known_drugs:
        pattern = re.compile(rf"(?<!\w){re.escape(drug_name)}(?!\w)", re.IGNORECASE)
        for match in pattern.finditer(raw_text):
            matches.append((match.start(), match.end(), match.group(0)))
    matches.sort(key=lambda item: (item[0], -(item[1] - item[0])))

    selected = []
    occupied_until = -1
    for match in matches:
        if match[0] < occupied_until:
            continue
        selected.append(match)
        occupied_until = match[1]

    if not selected:
        return {"status": "MANUAL_ENTRY_REQUIRED", "orders": []}

    orders = []
    for index, (start, end, medication_text) in enumerate(selected):
        next_start = selected[index + 1][0] if index + 1 < len(selected) else len(raw_text)
        medication_instructions = raw_text[end:next_start]
        dose, unit = extract_dose_and_unit(medication_instructions)
        frequency = extract_frequency(medication_instructions)
        duration = extract_duration(medication_instructions)
        orders.append({
            "medication_name": medication_text,
            "dose": dose,
            "unit": None if unit in (None, "Unknown") else unit,
            "route": None,
            "frequency": None if frequency == "Not specified" else frequency,
            "duration": None if duration == "Not specified" else duration,
            "indication": None,
        })

    return {"status": "DRAFT_REVIEW_REQUIRED", "orders": orders}
