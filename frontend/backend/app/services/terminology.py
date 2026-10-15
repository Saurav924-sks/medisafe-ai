"""Medication terminology providers with fail-closed normalization results."""
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Protocol

from thefuzz import fuzz


NORMALIZATION_REVIEW_MESSAGE = "Medication could not be confidently normalized"
DEFAULT_CONFIDENCE_THRESHOLD = 0.95
DEFAULT_AMBIGUITY_MARGIN = 0.05


@dataclass(frozen=True)
class NormalizationResult:
    canonical_entity: dict | None
    confidence: float | None
    match_method: str
    status: str
    message: str | None
    provider: str
    candidates: tuple[dict, ...] = ()

    def as_dict(self) -> dict:
        result = asdict(self)
        result["candidates"] = list(self.candidates)
        return result


class TerminologyProvider(Protocol):
    provider_name: str

    def normalize(self, medication_text: str) -> NormalizationResult:
        """Resolve input only when evidence meets this provider's criteria."""


def _normalize_text(value: str) -> str:
    return " ".join(value.casefold().split())


class LocalTerminologyProvider:
    provider_name = "local_drug_knowledge"

    def __init__(
        self,
        dataset_path: str | Path | None = None,
        knowledge_data: dict | None = None,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        ambiguity_margin: float = DEFAULT_AMBIGUITY_MARGIN,
    ) -> None:
        if dataset_path is None:
            dataset_path = Path(__file__).resolve().parents[3] / "knowledge_base" / "versions" / "v1.json"
        self.dataset_path = Path(dataset_path)
        self.knowledge_data = knowledge_data
        self.confidence_threshold = confidence_threshold
        self.ambiguity_margin = ambiguity_margin
        self._records: list[dict] | None = None

    def _load_records(self) -> list[dict]:
        try:
            data = self.knowledge_data if self.knowledge_data is not None else json.loads(self.dataset_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("manifest"), dict):
                data = data["data"]
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("Local medication terminology data is unavailable") from exc

        records = []
        for name, details in data.get("drugs", {}).items():
            ingredient = details.get("active_ingredient")
            records.append({
                "concept_id": details.get("concept_id"),
                "code_system": details.get("code_system"),
                "name": name,
                "ingredients": ([{
                    "concept_id": details.get("ingredient_concept_id"),
                    "name": ingredient,
                }] if ingredient else []),
                "strength": {
                    "value": details.get("strength_value"),
                    "unit": details.get("strength_unit"),
                },
                "dose_form": details.get("dose_form"),
                "route": details.get("route"),
                "therapeutic_class": details.get("class"),
                "source": self.provider_name,
            })
        if not records:
            raise RuntimeError("Local medication terminology data contains no medication records")
        return records

    def normalize(self, medication_text: str) -> NormalizationResult:
        if self._records is None:
            self._records = self._load_records()
        query = _normalize_text(medication_text)
        if not query:
            return self._review_result(0.0, "EMPTY_INPUT")

        exact_name = [record for record in self._records if _normalize_text(record["name"]) == query]
        if len(exact_name) == 1:
            return self._matched(exact_name[0], 1.0, "EXACT_NAME")
        if len(exact_name) > 1:
            return self._ambiguous(exact_name, 1.0, "EXACT_NAME")

        exact_ingredient = [
            record for record in self._records
            if any(_normalize_text(ingredient["name"]) == query for ingredient in record["ingredients"])
        ]
        if len(exact_ingredient) == 1:
            return self._matched(exact_ingredient[0], 0.98, "EXACT_INGREDIENT")
        if len(exact_ingredient) > 1:
            return self._ambiguous(exact_ingredient, 0.98, "EXACT_INGREDIENT")

        scored = []
        for record in self._records:
            aliases = [record["name"], *(item["name"] for item in record["ingredients"])]
            score = max(fuzz.ratio(query, _normalize_text(alias)) for alias in aliases)
            scored.append((score / 100.0, record))
        scored.sort(key=lambda item: item[0], reverse=True)

        if not scored or scored[0][0] < self.confidence_threshold:
            confidence = scored[0][0] if scored else 0.0
            return self._review_result(confidence, "BELOW_CONFIDENCE_THRESHOLD")

        best_confidence, best_record = scored[0]
        tied_records = [record for score, record in scored if best_confidence - score < self.ambiguity_margin]
        if len(tied_records) > 1:
            return self._ambiguous(tied_records, best_confidence, "AMBIGUOUS_FUZZY_MATCH")

        return self._matched(best_record, best_confidence, "FUZZY_NAME")

    def _matched(self, record: dict, confidence: float, method: str) -> NormalizationResult:
        return NormalizationResult(
            canonical_entity=record,
            confidence=confidence,
            match_method=method,
            status="NORMALIZED",
            message=None,
            provider=self.provider_name,
        )

    def _ambiguous(self, records: list[dict], confidence: float, method: str) -> NormalizationResult:
        return NormalizationResult(
            canonical_entity=None,
            confidence=confidence,
            match_method=method,
            status="AMBIGUOUS",
            message=NORMALIZATION_REVIEW_MESSAGE,
            provider=self.provider_name,
            candidates=tuple(records),
        )

    def _review_result(self, confidence: float, method: str) -> NormalizationResult:
        return NormalizationResult(
            canonical_entity=None,
            confidence=confidence,
            match_method=method,
            status="REVIEW_REQUIRED",
            message=NORMALIZATION_REVIEW_MESSAGE,
            provider=self.provider_name,
        )


class ExternalTerminologyProvider:
    """Integration seam for RxNorm or a jurisdiction-specific terminology API."""

    def __init__(self, jurisdiction: str = "unspecified") -> None:
        self.jurisdiction = jurisdiction
        self.provider_name = f"external:{jurisdiction}"

    def normalize(self, medication_text: str) -> NormalizationResult:
        return NormalizationResult(
            canonical_entity=None,
            confidence=None,
            match_method="EXTERNAL_PROVIDER_NOT_CONFIGURED",
            status="NOT_AVAILABLE",
            message=NORMALIZATION_REVIEW_MESSAGE,
            provider=self.provider_name,
        )


class MedicationTerminologyService:
    def __init__(
        self,
        local_provider: TerminologyProvider | None = None,
        external_provider: TerminologyProvider | None = None,
    ) -> None:
        self.local_provider = local_provider or LocalTerminologyProvider()
        self.external_provider = external_provider or ExternalTerminologyProvider()

    def normalize(self, medication_text: str, knowledge_data: dict | None = None) -> NormalizationResult:
        try:
            provider = LocalTerminologyProvider(knowledge_data=knowledge_data) if knowledge_data is not None else self.local_provider
            return provider.normalize(medication_text)
        except RuntimeError:
            return NormalizationResult(
                canonical_entity=None,
                confidence=None,
                match_method="LOCAL_REFERENCE_UNAVAILABLE",
                status="NOT_AVAILABLE",
                message=NORMALIZATION_REVIEW_MESSAGE,
                provider=self.local_provider.provider_name,
            )


medication_terminology = MedicationTerminologyService()
