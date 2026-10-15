"""Deprecated compatibility entry point; all FHIR handling delegates to the versioned adapter."""
from typing import Any

from app.interop.fhir.adapter import FHIR_ADAPTER_VERSION, FHIRValidationError, normalize_bundle, validate_bundle


def parse_fhir_bundle(fhir_bundle: Any) -> dict[str, Any]:
    """Validate and return the canonical representation without guessing terminology.

    Callers needing medication analysis must supply a configured terminology normalizer
    through `normalize_bundle`; this shim deliberately cannot certify medication names.
    """
    return normalize_bundle(
        fhir_bundle,
        lambda _display: {"canonical_entity": None, "status": "NOT_AVAILABLE", "provider": None},
    )


__all__ = ["FHIR_ADAPTER_VERSION", "FHIRValidationError", "normalize_bundle", "parse_fhir_bundle", "validate_bundle"]
