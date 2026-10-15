import re
from decimal import Decimal
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

# --- Patient Schemas ---
class AllergyCreate(BaseModel):
    allergy_name: str = Field(..., min_length=1, max_length=100, description="Name of the allergy")

class ConditionCreate(BaseModel):
    condition_name: str = Field(..., min_length=1, max_length=100, description="Name of the condition")

class MedicationCreate(BaseModel):
    medication_name: str = Field(..., min_length=1, max_length=100)
    dose: Optional[str] = Field(None, max_length=50)
    frequency: Optional[str] = Field(None, max_length=50)

class PatientCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    age: int = Field(..., ge=0, le=120, description="Age must be between 0 and 120")
    gender: str = Field(..., min_length=1, max_length=20)

class PatientResponse(PatientCreate):
    id: int
    allergies: List[AllergyCreate] = []
    conditions: List[ConditionCreate] = []
    current_meds: List[MedicationCreate] = []

    model_config = {"from_attributes": True}

# --- Prescription Schemas ---
class PrescriptionItemCreate(BaseModel):
    drug_name: str = Field(..., min_length=1, max_length=100)
    dose: Optional[str] = Field(None, max_length=50)
    unit: Optional[str] = Field(None, max_length=20)
    frequency: Optional[str] = Field(None, max_length=50)
    duration: Optional[str] = Field(None, max_length=50)

class PrescriptionCreate(BaseModel):
    patient_id: int
    # Limit raw text to 2000 characters to prevent abuse/DoS
    raw_text: Optional[str] = Field(None, max_length=2000)
    items: List[PrescriptionItemCreate]


class MedicationRoute(str, Enum):
    ORAL = "oral"
    INTRAVENOUS = "intravenous"
    INTRAMUSCULAR = "intramuscular"
    SUBCUTANEOUS = "subcutaneous"
    TOPICAL = "topical"
    INHALATION = "inhalation"
    RECTAL = "rectal"
    OPHTHALMIC = "ophthalmic"
    OTIC = "otic"
    SUBLINGUAL = "sublingual"
    TRANSDERMAL = "transdermal"


class MedicationDoseUnit(str, Enum):
    MG = "mg"
    MCG = "mcg"
    G = "g"
    ML = "mL"
    UNIT = "unit"
    TABLET = "tablet"
    CAPSULE = "capsule"


class AlertReviewActionType(str, Enum):
    REVIEW = "REVIEW"
    ACKNOWLEDGE = "ACKNOWLEDGE"
    OVERRIDE = "OVERRIDE"
    RESOLVE = "RESOLVE"
    DISMISS = "DISMISS"


class OverrideReason(str, Enum):
    CLINICAL_JUDGMENT = "CLINICAL_JUDGMENT"
    PATIENT_CONTEXT_NOT_CAPTURED = "PATIENT_CONTEXT_NOT_CAPTURED"
    DUPLICATE_OR_ALREADY_ADDRESSED = "DUPLICATE_OR_ALREADY_ADDRESSED"
    REFERENCE_DATA_ISSUE = "REFERENCE_DATA_ISSUE"
    OTHER = "OTHER"


class AlertFeedbackValue(str, Enum):
    AGREE = "AGREE"
    DISAGREE = "DISAGREE"
    OVERRIDE = "OVERRIDE"
    UNKNOWN = "UNKNOWN"


FREQUENCY_CANONICAL = {
    "once": "Once",
    "once daily": "Once daily",
    "daily": "Once daily",
    "od": "Once daily",
    "twice daily": "Twice daily",
    "bid": "Twice daily",
    "three times daily": "Three times daily",
    "tid": "Three times daily",
    "four times daily": "Four times daily",
    "qid": "Four times daily",
    "every 4 hours": "Every 4 hours",
    "every 6 hours": "Every 6 hours",
    "every 8 hours": "Every 8 hours",
    "every 12 hours": "Every 12 hours",
    "as needed": "As needed",
    "prn": "As needed",
}


class MedicationOrderInput(BaseModel):
    medication_name: str = Field(..., min_length=1, max_length=240)
    dose: Decimal = Field(..., gt=0, max_digits=12, decimal_places=6)
    unit: MedicationDoseUnit
    route: MedicationRoute
    frequency: str = Field(..., min_length=1, max_length=100)
    duration: Optional[str] = Field(None, max_length=100)
    indication: Optional[str] = Field(None, max_length=500)

    @field_validator("medication_name")
    @classmethod
    def medication_name_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("medication_name must not be blank")
        return value

    @field_validator("frequency")
    @classmethod
    def validate_frequency(cls, value: str) -> str:
        canonical = FREQUENCY_CANONICAL.get(" ".join(value.casefold().split()))
        if canonical is None:
            raise ValueError("frequency is not in the supported structured frequency set")
        return canonical

    @field_validator("duration")
    @classmethod
    def validate_duration(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        value = value.strip()
        if not value or not re.fullmatch(r"\d+(?:\.\d+)?\s+(?:days?|weeks?|months?)", value, re.IGNORECASE):
            raise ValueError("duration must use a positive count followed by days, weeks, or months")
        return value


class PrescriptionCreateRequest(BaseModel):
    patient_id: int = Field(..., gt=0)
    raw_text: Optional[str] = Field(None, max_length=2000)
    medication_orders: List[MedicationOrderInput] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def require_text_or_structured_orders(self):
        if not (self.raw_text and self.raw_text.strip()) and not self.medication_orders:
            raise ValueError("Provide raw_text for draft parsing or at least one structured medication order")
        return self


class MedicationOrderResponse(BaseModel):
    id: int
    medication_name: str
    dose: Optional[str]
    unit: Optional[str]
    route: Optional[str]
    frequency: Optional[str]
    duration: Optional[str]
    indication: Optional[str]
    status: str
    normalization_status: str
    normalization_confidence: Optional[float]
    match_method: Optional[str]
    normalization_message: Optional[str]
    canonical_entity: Optional[dict]
    normalization_confirmed: bool = False
    clinician_review_required: bool


class PrescriptionResponse(BaseModel):
    id: int
    patient_id: int
    status: str
    parser_status: str
    raw_text: Optional[str]
    created_at: Optional[str]
    clinician_review_required: bool
    orders: List[MedicationOrderResponse]


class AlertReviewActionCreate(BaseModel):
    action: AlertReviewActionType
    override_reason: Optional[OverrideReason] = None
    override_reason_text: Optional[str] = Field(None, max_length=1000)
    note: Optional[str] = Field(None, max_length=1000)


class AlertFeedbackCreate(BaseModel):
    analysis_id: int = Field(..., gt=0)
    feedback: AlertFeedbackValue
    rationale: Optional[str] = Field(None, max_length=2000)


class KnowledgeReviewRequest(BaseModel):
    review_note: str = Field(..., min_length=10, max_length=2000)


class KnowledgeActivationRequest(BaseModel):
    expected_active_version_id: Optional[int] = Field(..., ge=1)


class AlertReviewActionResponse(BaseModel):
    id: int
    analysis_id: int
    alert_id: int
    clinician_id: int
    action: str
    override_reason: Optional[str]
    override_reason_text: Optional[str]
    rule_version: Optional[str]
    knowledge_base_version: Optional[str]
    created_at: str


class FeedbackCreate(BaseModel):
    alert_index: int
    override_decision: Optional[bool] = None  # True = clinician overrides/accepts alert, False = rejects
    clinician_note: Optional[str] = Field(None, max_length=1000)
    alert_type: Optional[str] = Field(None, max_length=100)  # e.g., "Allergy Conflict"
    drug_name: Optional[str] = Field(None, max_length=100)   # primary drug involved


class FeedbackAnalyticsResponse(BaseModel):
    total_feedback: int
    agreement_rate: float
    disagreement_rate: float
    per_type_stats: dict
    adapted_types: List[str]
    system_version: str


class AdaptedAnalysisResponse(BaseModel):
    id: int
    score: int
    risk_level: str
    total_alerts: int
    disclaimer: str
    alerts: List[dict]
    score_breakdown: List[dict]
    feedback_adapted: bool = False
    adapted_types: List[str] = []
