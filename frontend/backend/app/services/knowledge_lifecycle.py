"""Offline validation and normalization for governed clinical knowledge files."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date
from typing import Any

from fastapi import HTTPException


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def checksum(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value)).hexdigest()


def _trusted_sources() -> set[str]:
    configured = os.getenv("TRUSTED_KNOWLEDGE_SOURCES", "Existing prototype knowledge graph")
    return {item.strip() for item in configured.split(",") if item.strip()}


def validate_and_normalize(document: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], str]:
    """Check an imported JSON file and return manifest, canonical data, checksum."""
    if not isinstance(document, dict) or not isinstance(document.get("manifest"), dict):
        raise HTTPException(status_code=422, detail="Knowledge file must contain manifest and data objects.")
    manifest = document["manifest"]
    data = document.get("data")
    required = ("dataset", "version", "source", "source_version", "evidence_reference", "checksum")
    if any(not isinstance(manifest.get(key), str) or not manifest[key].strip() for key in required):
        raise HTTPException(status_code=422, detail="Knowledge provenance is incomplete.")
    if "effective_date" not in manifest or "last_reviewed" not in manifest:
        raise HTTPException(status_code=422, detail="Knowledge file must state effective_date and last_reviewed, using null when unknown.")
    if manifest["source"] not in _trusted_sources():
        raise HTTPException(status_code=422, detail="Knowledge source is not on the configured trusted-source allowlist.")
    try:
        effective_date = date.fromisoformat(manifest["effective_date"]) if manifest.get("effective_date") else None
        last_reviewed = date.fromisoformat(manifest["last_reviewed"]) if manifest.get("last_reviewed") else None
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Knowledge provenance dates must use ISO YYYY-MM-DD format.") from exc
    if not isinstance(data, dict) or not isinstance(data.get("drugs"), dict) or not data["drugs"]:
        raise HTTPException(status_code=422, detail="Knowledge data must contain a non-empty drugs object.")
    supported_data_keys = {
        "drugs", "drug_drug_interactions", "drug_disease_contraindications",
        "allergy_cross_reactivity", "duplicate_therapeutic_classes",
        "duplicate_medication_rule", "dosage_limit_rule", "dosage_verification_rule",
        "priority_scoring", "explanation_templates",
    }
    if set(data) - supported_data_keys:
        raise HTTPException(status_code=422, detail="Knowledge data contains unsupported fields; import would otherwise discard content.")

    expected_checksum = checksum(data)
    if manifest["checksum"] != expected_checksum:
        raise HTTPException(status_code=422, detail="Knowledge checksum does not match file data.")

    severity_values = {"CRITICAL", "HIGH", "MODERATE", "LOW", "MILD", "INFORMATIONAL", "UNKNOWN", "NOT_AVAILABLE"}
    normalized = {"drugs": {}, "drug_drug_interactions": [], "drug_disease_contraindications": [], "allergy_cross_reactivity": [], "duplicate_therapeutic_classes": []}
    if "duplicate_medication_rule" in data:
        duplicate_rule = data["duplicate_medication_rule"]
        if not isinstance(duplicate_rule, dict) or not isinstance(duplicate_rule.get("severity"), str) or duplicate_rule["severity"].upper() not in severity_values:
            raise HTTPException(status_code=422, detail="duplicate_medication_rule requires a supported severity.")
        if not isinstance(duplicate_rule.get("reason"), str) or not duplicate_rule["reason"].strip():
            raise HTTPException(status_code=422, detail="duplicate_medication_rule requires a rationale.")
        normalized["duplicate_medication_rule"] = {**duplicate_rule, "severity": duplicate_rule["severity"].upper()}
    for name, details in data["drugs"].items():
        if not isinstance(name, str) or not name.strip() or not isinstance(details, dict):
            raise HTTPException(status_code=422, detail="Each drug record requires a name and object data.")
        maximum = details.get("max_daily_dose_mg")
        if maximum is not None and (not isinstance(maximum, (int, float)) or maximum <= 0):
            raise HTTPException(status_code=422, detail=f"Drug {name!r} has an invalid configured dose limit.")
        normalized["drugs"][" ".join(name.split())] = details

    table_requirements = {
        "drug_drug_interactions": ("drug_a", "drug_b"),
        "drug_disease_contraindications": ("drug", "disease"),
        "allergy_cross_reactivity": ("allergen", "trigger_drug"),
        "duplicate_therapeutic_classes": ("class",),
    }
    for table, keys in table_requirements.items():
        rows = data.get(table, [])
        if not isinstance(rows, list):
            raise HTTPException(status_code=422, detail=f"{table} must be a list.")
        seen = set()
        for row in rows:
            if not isinstance(row, dict) or any(not isinstance(row.get(key), str) or not row[key].strip() for key in keys):
                raise HTTPException(status_code=422, detail=f"Each {table} entry must include {', '.join(keys)}.")
            severity = row.get("severity")
            if not isinstance(severity, str) or severity.upper() not in severity_values:
                raise HTTPException(status_code=422, detail=f"Each {table} entry requires a supported severity.")
            if not isinstance(row.get("reason"), str) or not row["reason"].strip():
                raise HTTPException(status_code=422, detail=f"Each {table} entry requires a rationale.")
            identity = tuple(" ".join(row[key].split()).casefold() for key in keys)
            if identity in seen:
                raise HTTPException(status_code=422, detail=f"Duplicate entry found in {table}.")
            seen.add(identity)
            normalized_row = dict(row)
            for key in keys:
                normalized_row[key] = " ".join(row[key].split())
            normalized_row["severity"] = severity.upper()
            normalized[table].append(normalized_row)

    for key in ("priority_scoring", "explanation_templates"):
        if key in data:
            if not isinstance(data[key], dict):
                raise HTTPException(status_code=422, detail=f"{key} must be an object.")
            normalized[key] = data[key]
    if "priority_scoring" in data:
        scoring = data["priority_scoring"]
        points = scoring.get("severity_points")
        levels = scoring.get("risk_levels")
        maximum = scoring.get("max_score")
        if (
            not isinstance(points, dict) or not points
            or any(not isinstance(value, int) or value < 0 for value in points.values())
            or not isinstance(levels, list) or not levels
            or not isinstance(maximum, int) or maximum <= 0
        ):
            raise HTTPException(status_code=422, detail="priority_scoring has an invalid schema.")
        for level in levels:
            if (
                not isinstance(level, dict)
                or not isinstance(level.get("minimum"), int)
                or not isinstance(level.get("maximum"), int)
                or level["minimum"] > level["maximum"]
                or not isinstance(level.get("label"), str)
                or not level["label"].strip()
            ):
                raise HTTPException(status_code=422, detail="priority_scoring risk_levels has an invalid entry.")
    for key in ("dosage_limit_rule", "dosage_verification_rule"):
        if key in data:
            rule = data[key]
            if not isinstance(rule, dict) or not isinstance(rule.get("severity"), str) or rule["severity"].upper() not in severity_values:
                raise HTTPException(status_code=422, detail=f"{key} requires a supported severity.")
            if not isinstance(rule.get("evidence_reference"), str) or not rule["evidence_reference"].strip():
                raise HTTPException(status_code=422, detail=f"{key} requires an evidence reference.")
            if not any(isinstance(rule.get(field), str) and rule[field].strip() for field in ("reason", "reason_template")):
                raise HTTPException(status_code=422, detail=f"{key} requires a rationale.")
            normalized[key] = {**rule, "severity": rule["severity"].upper()}
    for key in ("dosage_limit_rule", "dosage_verification_rule"):
        if key in data:
            rule = data[key]
            if not isinstance(rule, dict) or not isinstance(rule.get("severity"), str) or rule["severity"].upper() not in severity_values:
                raise HTTPException(status_code=422, detail=f"{key} requires a supported severity.")
            if not isinstance(rule.get("evidence_reference"), str) or not rule["evidence_reference"].strip():
                raise HTTPException(status_code=422, detail=f"{key} requires an evidence reference.")
            if not any(isinstance(rule.get(field), str) and rule[field].strip() for field in ("reason", "reason_template")):
                raise HTTPException(status_code=422, detail=f"{key} requires a rationale.")
            normalized[key] = {**rule, "severity": rule["severity"].upper()}

    normalized_manifest = dict(manifest)
    normalized_manifest["dataset"] = manifest["dataset"].strip()
    normalized_manifest["version"] = manifest["version"].strip()
    normalized_manifest["source"] = manifest["source"].strip()
    normalized_manifest["source_version"] = manifest["source_version"].strip()
    normalized_manifest["effective_date"] = effective_date.isoformat() if effective_date else None
    normalized_manifest["last_reviewed"] = last_reviewed.isoformat() if last_reviewed else None
    return normalized_manifest, normalized, checksum(normalized)
