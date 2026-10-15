from datetime import date, datetime, timezone
from enum import Enum

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Enum as SqlEnum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    event,
    func,
    inspect,
    text,
)
from sqlalchemy.orm import Session, relationship

from app.core.database import Base


class DataStatus(str, Enum):
    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"
    NOT_AVAILABLE = "NOT_AVAILABLE"


class PregnancyStatus(str, Enum):
    PREGNANT = "PREGNANT"
    NOT_PREGNANT = "NOT_PREGNANT"
    UNKNOWN = "UNKNOWN"
    NOT_AVAILABLE = "NOT_AVAILABLE"


class AllergyDataStatus(str, Enum):
    KNOWN = "KNOWN"
    NONE_REPORTED = "NONE_REPORTED"
    UNKNOWN = "UNKNOWN"
    NOT_AVAILABLE = "NOT_AVAILABLE"


class AllergyCategory(str, Enum):
    MEDICATION = "MEDICATION"
    FOOD = "FOOD"
    ENVIRONMENTAL = "ENVIRONMENTAL"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class AllergyClinicalStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    RESOLVED = "RESOLVED"
    ENTERED_IN_ERROR = "ENTERED_IN_ERROR"
    UNKNOWN = "UNKNOWN"


class VerificationStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    SUSPECTED = "SUSPECTED"
    HISTORICAL = "HISTORICAL"
    UNKNOWN = "UNKNOWN"
    NOT_AVAILABLE = "NOT_AVAILABLE"


class ClinicalStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    RESOLVED = "RESOLVED"
    REMISSION = "REMISSION"
    UNKNOWN = "UNKNOWN"


class ClinicalSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MODERATE = "MODERATE"
    LOW = "LOW"
    MILD = "MILD"
    UNKNOWN = "UNKNOWN"
    NOT_AVAILABLE = "NOT_AVAILABLE"


class MedicationStatus(str, Enum):
    CURRENT = "CURRENT"
    STOPPED = "STOPPED"
    HISTORICAL = "HISTORICAL"
    UNKNOWN = "UNKNOWN"
    NOT_AVAILABLE = "NOT_AVAILABLE"


class MedicationOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    ON_HOLD = "ON_HOLD"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    STOPPED = "STOPPED"
    UNKNOWN = "UNKNOWN"


class AnalysisStatus(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIALLY_EVALUATED = "PARTIALLY_EVALUATED"
    INCOMPLETE = "INCOMPLETE"
    FAILED = "FAILED"


class DomainStatus(str, Enum):
    EVALUATED = "EVALUATED"
    NOT_EVALUATED = "NOT_EVALUATED"
    FAILED = "FAILED"


class RuleStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class KnowledgeStatus(str, Enum):
    LOADED = "LOADED"
    INACTIVE = "INACTIVE"
    UNAVAILABLE = "UNAVAILABLE"


class AlertStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    OVERRIDDEN = "OVERRIDDEN"
    RESOLVED = "RESOLVED"
    UNKNOWN = "UNKNOWN"


class FeedbackDecision(str, Enum):
    AGREE = "AGREE"
    DISAGREE = "DISAGREE"
    OVERRIDE = "OVERRIDE"
    UNKNOWN = "UNKNOWN"


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


def enum_column(enum_class, name, **kwargs):
    return Column(
        SqlEnum(
            enum_class,
            name=name,
            native_enum=False,
            create_constraint=True,
            values_callable=lambda members: [member.value for member in members],
        ),
        **kwargs,
    )


class RecordMetadata:
    created_at = Column(DateTime(timezone=True), nullable=True, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=func.now())
    created_by = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    updated_by = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)


class SoftDeleteMixin:
    is_active = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    deactivated_at = Column(DateTime(timezone=True), nullable=True)
    deactivated_by = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)

    def deactivate(self, actor_id=None, at=None):
        self.is_active = False
        self.deactivated_by = actor_id
        self.deactivated_at = at or datetime.now(timezone.utc)


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False, unique=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=func.now())
    created_by = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT", use_alter=True, name="fk_organizations_created_by"), nullable=True)
    updated_by = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT", use_alter=True, name="fk_organizations_updated_by"), nullable=True)
    deactivated_at = Column(DateTime(timezone=True), nullable=True)
    deactivated_by = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT", use_alter=True, name="fk_organizations_deactivated_by"), nullable=True)

    def deactivate(self, actor_id=None, at=None):
        self.is_active = False
        self.deactivated_by = actor_id
        self.deactivated_at = at or datetime.now(timezone.utc)


class Role(RecordMetadata, SoftDeleteMixin, Base):
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True)
    name = Column(String(40), nullable=False, unique=True)
    description = Column(String(250), nullable=True)


class User(RecordMetadata, SoftDeleteMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("organization_id", "email_normalized", name="uq_users_org_email"),
        Index("ix_users_org_active", "organization_id", "is_active"),
    )

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    email = Column(String(320), nullable=True)
    email_normalized = Column(String(320), nullable=True)
    display_name = Column(String(200), nullable=False)


class UserRole(RecordMetadata, Base):
    __tablename__ = "user_roles"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True)
    role_id = Column(Integer, ForeignKey("roles.id", ondelete="RESTRICT"), primary_key=True)


class Encounter(RecordMetadata, SoftDeleteMixin, Base):
    __tablename__ = "encounters"
    __table_args__ = (
        UniqueConstraint("organization_id", "external_id", name="uq_encounters_org_external_id"),
        Index("ix_encounters_patient_started", "patient_id", "started_at"),
    )

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False)
    external_id = Column(String(120), nullable=True)
    encounter_type = Column(String(80), nullable=True)
    status = Column(String(40), nullable=False, default="UNKNOWN", server_default="UNKNOWN")
    started_at = Column(DateTime(timezone=True), nullable=True)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    source = Column(String(120), nullable=True)


class Observation(RecordMetadata, SoftDeleteMixin, Base):
    __tablename__ = "observations"
    __table_args__ = (
        Index("ix_observations_patient_code_time", "patient_id", "code", "observed_at"),
        CheckConstraint(
            "(availability_status = 'KNOWN' AND (value_number IS NOT NULL OR value_text IS NOT NULL)) "
            "OR (availability_status <> 'KNOWN' AND value_number IS NULL AND value_text IS NULL)",
            name="ck_observations_value_matches_status",
        ),
    )

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False)
    encounter_id = Column(Integer, ForeignKey("encounters.id", ondelete="RESTRICT"), nullable=True)
    code = Column(String(120), nullable=False)
    code_system = Column(String(200), nullable=True)
    availability_status = enum_column(
        DataStatus, "observation_data_status", nullable=False, default=DataStatus.NOT_AVAILABLE,
        server_default=DataStatus.NOT_AVAILABLE.value,
    )
    value_number = Column(Numeric(18, 6), nullable=True)
    value_text = Column(Text, nullable=True)
    unit = Column(String(80), nullable=True)
    observed_at = Column(DateTime(timezone=True), nullable=True)
    source = Column(String(120), nullable=True)


class PatientIdentifier(RecordMetadata, SoftDeleteMixin, Base):
    __tablename__ = "patient_identifiers"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "identifier_type", "normalized_value",
            name="uq_patient_identifier_org_type_value",
        ),
        Index("ix_patient_identifiers_patient", "patient_id"),
    )

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False)
    identifier_type = Column(String(40), nullable=False)
    value = Column(String(160), nullable=False)
    normalized_value = Column(String(160), nullable=False)
    is_primary = Column(Boolean, nullable=False, default=False, server_default=text("0"))


class Allergy(RecordMetadata, SoftDeleteMixin, Base):
    __tablename__ = "allergies"
    __table_args__ = (
        Index("ix_allergies_patient_status", "patient_id", "clinical_status", "verification_status"),
    )

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False)
    encounter_id = Column(Integer, ForeignKey("encounters.id", ondelete="RESTRICT"), nullable=True)
    substance = Column(String(200), nullable=False)
    category = enum_column(AllergyCategory, "allergy_category", nullable=False, default=AllergyCategory.UNKNOWN)
    reaction = Column(Text, nullable=True)
    severity = enum_column(ClinicalSeverity, "allergy_severity", nullable=False, default=ClinicalSeverity.UNKNOWN)
    clinical_status = enum_column(
        AllergyClinicalStatus, "allergy_clinical_status", nullable=False,
        default=AllergyClinicalStatus.UNKNOWN,
    )
    verification_status = enum_column(
        VerificationStatus, "allergy_verification_status", nullable=False,
        default=VerificationStatus.UNKNOWN,
    )
    onset = Column(Date, nullable=True)
    notes = Column(Text, nullable=True)
    source = Column(String(120), nullable=True)
    recorded_by = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    recorded_at = Column(DateTime(timezone=True), nullable=True, server_default=func.now())
    changes = relationship("AllergyChange", back_populates="allergy", order_by="AllergyChange.created_at")


class AllergyChange(Base):
    __tablename__ = "allergy_changes"
    __table_args__ = (Index("ix_allergy_changes_allergy_time", "allergy_id", "created_at"),)

    id = Column(Integer, primary_key=True)
    allergy_id = Column(Integer, ForeignKey("allergies.id", ondelete="RESTRICT"), nullable=False)
    change_type = Column(String(24), nullable=False)
    changed_fields = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_by = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    allergy = relationship("Allergy", back_populates="changes")


class Condition(RecordMetadata, SoftDeleteMixin, Base):
    __tablename__ = "conditions"
    __table_args__ = (Index("ix_conditions_patient_status", "patient_id", "clinical_status"),)

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False)
    encounter_id = Column(Integer, ForeignKey("encounters.id", ondelete="RESTRICT"), nullable=True)
    name = Column(String(200), nullable=False)
    code = Column(String(120), nullable=True)
    code_system = Column(String(200), nullable=True)
    clinical_status = enum_column(ClinicalStatus, "condition_clinical_status", nullable=False, default=ClinicalStatus.UNKNOWN)
    onset = Column(Date, nullable=True)
    severity = enum_column(ClinicalSeverity, "condition_severity", nullable=False, default=ClinicalSeverity.UNKNOWN)
    source = Column(String(120), nullable=True)


class Medication(RecordMetadata, SoftDeleteMixin, Base):
    __tablename__ = "medications"
    __table_args__ = (
        UniqueConstraint("normalized_name", name="uq_medications_normalized_name"),
        UniqueConstraint("code_system", "code", name="uq_medications_code_system_code"),
        Index("ix_medications_active_name", "is_active", "normalized_name"),
    )

    id = Column(Integer, primary_key=True)
    name = Column(String(240), nullable=False)
    normalized_name = Column(String(240), nullable=False)
    code = Column(String(120), nullable=True)
    code_system = Column(String(200), nullable=True)
    strength_value = Column(Numeric(18, 6), nullable=True)
    strength_unit = Column(String(80), nullable=True)
    dose_form = Column(String(120), nullable=True)
    route = Column(String(80), nullable=True)
    catalog_status = enum_column(DataStatus, "medication_catalog_status", nullable=False, default=DataStatus.UNKNOWN)
    source = Column(String(120), nullable=True)


class MedicationIngredient(RecordMetadata, SoftDeleteMixin, Base):
    __tablename__ = "medication_ingredients"
    __table_args__ = (
        UniqueConstraint("medication_id", "normalized_name", name="uq_medication_ingredient_name"),
        Index("ix_medication_ingredients_code", "code_system", "code"),
    )

    id = Column(Integer, primary_key=True)
    medication_id = Column(Integer, ForeignKey("medications.id", ondelete="RESTRICT"), nullable=False)
    name = Column(String(240), nullable=False)
    normalized_name = Column(String(240), nullable=False)
    code = Column(String(120), nullable=True)
    code_system = Column(String(200), nullable=True)
    strength_value = Column(Numeric(18, 6), nullable=True)
    strength_unit = Column(String(80), nullable=True)
    source = Column(String(120), nullable=True)


class MedicationHistory(RecordMetadata, SoftDeleteMixin, Base):
    __tablename__ = "medication_history"
    __table_args__ = (
        Index("ix_medication_history_patient_status", "patient_id", "status"),
        Index("ix_medication_history_verified", "patient_id", "last_verified_at"),
    )

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False)
    medication_id = Column(Integer, ForeignKey("medications.id", ondelete="RESTRICT"), nullable=False)
    status = enum_column(MedicationStatus, "medication_history_status", nullable=False, default=MedicationStatus.UNKNOWN)
    medication_name_snapshot = Column(String(240), nullable=False)
    dose = Column(String(100), nullable=True)
    frequency = Column(String(100), nullable=True)
    indication = Column(String(500), nullable=True)
    prescriber_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    source = Column(String(120), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    last_verified_at = Column(DateTime(timezone=True), nullable=True)


class MedicationOrder(RecordMetadata, SoftDeleteMixin, Base):
    __tablename__ = "medication_orders"
    __table_args__ = (
        UniqueConstraint("legacy_item_id", name="uq_medication_orders_legacy_item"),
        Index("ix_medication_orders_patient_status", "patient_id", "status"),
        CheckConstraint(
            "normalization_status IN ('NORMALIZED', 'AMBIGUOUS', 'REVIEW_REQUIRED', 'UNKNOWN', 'NOT_AVAILABLE')",
            name="ck_medication_orders_normalization_status",
        ),
    )

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False)
    encounter_id = Column(Integer, ForeignKey("encounters.id", ondelete="RESTRICT"), nullable=True)
    prescription_id = Column(Integer, ForeignKey("prescriptions.id", ondelete="RESTRICT"), nullable=True)
    medication_id = Column(Integer, ForeignKey("medications.id", ondelete="RESTRICT"), nullable=True)
    legacy_item_id = Column(Integer, nullable=True)
    medication_name_snapshot = Column(String(240), nullable=False)
    dose = Column(String(100), nullable=True)
    unit = Column(String(80), nullable=True)
    route = Column(String(80), nullable=True)
    frequency = Column(String(100), nullable=True)
    duration = Column(String(100), nullable=True)
    indication = Column(String(500), nullable=True)
    status = enum_column(MedicationOrderStatus, "medication_order_status", nullable=False, default=MedicationOrderStatus.UNKNOWN)
    prescriber_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    source = Column(String(120), nullable=True)
    last_verified_at = Column(DateTime(timezone=True), nullable=True)
    normalization_status = Column(String(32), nullable=False, default="NOT_AVAILABLE", server_default="NOT_AVAILABLE")
    normalization_confidence = Column(Numeric(5, 4), nullable=True)
    match_method = Column(String(64), nullable=True)
    normalization_message = Column(String(200), nullable=True)
    normalization_result = Column(JSON, nullable=True)
    prescription = relationship("Prescription", back_populates="orders")


class KnowledgeVersion(RecordMetadata, SoftDeleteMixin, Base):
    __tablename__ = "knowledge_versions"
    __table_args__ = (
        UniqueConstraint("dataset", "version", name="uq_knowledge_dataset_version"),
        Index("ix_knowledge_versions_status", "status"),
        Index(
            "uq_knowledge_one_active_per_dataset", "dataset", unique=True,
            sqlite_where=text("lifecycle_stage = 'ACTIVE'"),
            postgresql_where=text("lifecycle_stage = 'ACTIVE'"),
        ),
    )

    id = Column(Integer, primary_key=True)
    dataset = Column(String(120), nullable=False)
    version = Column(String(80), nullable=False)
    source = Column(String(240), nullable=True)
    source_version = Column(String(120), nullable=True)
    effective_date = Column(Date, nullable=True)
    last_reviewed = Column(Date, nullable=True)
    checksum = Column(String(128), nullable=True)
    status = enum_column(KnowledgeStatus, "knowledge_status", nullable=False, default=KnowledgeStatus.UNAVAILABLE)
    lifecycle_stage = Column(String(32), nullable=False, default="IMPORTED", server_default="IMPORTED")
    evidence_reference = Column(String(1000), nullable=True)
    review_note = Column(Text, nullable=True)
    reviewed_by = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    activated_by = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    activated_at = Column(DateTime(timezone=True), nullable=True)
    payload = Column(JSON, nullable=True)


class ClinicalRule(RecordMetadata, SoftDeleteMixin, Base):
    __tablename__ = "clinical_rules"
    __table_args__ = (
        UniqueConstraint("rule_id", "version", name="uq_clinical_rule_version"),
        Index("ix_clinical_rules_status_domain", "status", "domain"),
    )

    id = Column(Integer, primary_key=True)
    rule_id = Column(String(120), nullable=False)
    version = Column(String(80), nullable=False)
    source = Column(String(240), nullable=False)
    source_version = Column(String(120), nullable=False)
    effective_date = Column(Date, nullable=False)
    evidence_reference = Column(String(500), nullable=False)
    domain = Column(String(80), nullable=False)
    severity = enum_column(ClinicalSeverity, "clinical_rule_severity", nullable=False, default=ClinicalSeverity.UNKNOWN)
    trigger_conditions = Column(JSON, nullable=False)
    rationale = Column(Text, nullable=False)
    recommendation = Column(Text, nullable=False)
    status = enum_column(RuleStatus, "clinical_rule_status", nullable=False, default=RuleStatus.DRAFT)
    knowledge_version_id = Column(Integer, ForeignKey("knowledge_versions.id", ondelete="RESTRICT"), nullable=True)


class Analysis(RecordMetadata, SoftDeleteMixin, Base):
    __tablename__ = "analyses"
    __table_args__ = (
        Index("ix_analyses_patient_created", "patient_id", "created_at"),
        Index("ix_analyses_status", "status"),
    )

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False)
    encounter_id = Column(Integer, ForeignKey("encounters.id", ondelete="RESTRICT"), nullable=True)
    prescription_id = Column(Integer, ForeignKey("prescriptions.id", ondelete="RESTRICT"), nullable=True)
    status = enum_column(AnalysisStatus, "analysis_status", nullable=False, default=AnalysisStatus.INCOMPLETE, server_default=AnalysisStatus.INCOMPLETE.value)
    failure_reason = Column(String(500), nullable=True)
    knowledge_version_id = Column(Integer, ForeignKey("knowledge_versions.id", ondelete="RESTRICT"), nullable=True)
    rule_set_version = Column(String(120), nullable=True)
    allergy_checked = Column(Boolean, nullable=False, default=False, server_default=text("0"))
    drug_drug_checked = Column(Boolean, nullable=False, default=False, server_default=text("0"))
    drug_disease_checked = Column(Boolean, nullable=False, default=False, server_default=text("0"))
    dose_checked = Column(Boolean, nullable=False, default=False, server_default=text("0"))
    duplicate_therapy_checked = Column(Boolean, nullable=False, default=False, server_default=text("0"))
    renal_checked = Column(Boolean, nullable=False, default=False, server_default=text("0"))
    hepatic_checked = Column(Boolean, nullable=False, default=False, server_default=text("0"))
    pregnancy_checked = Column(Boolean, nullable=False, default=False, server_default=text("0"))
    age_checked = Column(Boolean, nullable=False, default=False, server_default=text("0"))
    other_domains = Column(JSON, nullable=False, default=dict)


class AnalysisRuleUsage(Base):
    __tablename__ = "analysis_rule_usages"
    __table_args__ = (
        UniqueConstraint("analysis_id", "clinical_rule_id", "rule_version", name="uq_analysis_rule_version"),
    )

    id = Column(Integer, primary_key=True)
    analysis_id = Column(Integer, ForeignKey("analyses.id", ondelete="RESTRICT"), nullable=False)
    clinical_rule_id = Column(Integer, ForeignKey("clinical_rules.id", ondelete="RESTRICT"), nullable=False)
    rule_version = Column(String(80), nullable=False)
    evaluation_status = enum_column(DomainStatus, "rule_evaluation_status", nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_by = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)


class Alert(RecordMetadata, SoftDeleteMixin, Base):
    __tablename__ = "alerts"
    __table_args__ = (
        UniqueConstraint("analysis_id", "alert_index", name="uq_alert_analysis_index"),
        Index("ix_alerts_analysis_severity", "analysis_id", "severity"),
    )

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    analysis_id = Column(Integer, ForeignKey("analyses.id", ondelete="RESTRICT"), nullable=False)
    clinical_rule_id = Column(Integer, ForeignKey("clinical_rules.id", ondelete="RESTRICT"), nullable=True)
    alert_index = Column(Integer, nullable=False)
    domain = Column(String(80), nullable=False)
    severity = enum_column(ClinicalSeverity, "alert_severity", nullable=False, default=ClinicalSeverity.UNKNOWN)
    status = enum_column(AlertStatus, "alert_status", nullable=False, default=AlertStatus.OPEN)
    message = Column(Text, nullable=False)
    evidence_reference = Column(String(500), nullable=True)
    source = Column(String(240), nullable=True)
    recommendation = Column(Text, nullable=True)
    details = Column(JSON, nullable=False, default=dict)
    acknowledged_by = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    override_reason = Column(Text, nullable=True)


class Feedback(RecordMetadata, SoftDeleteMixin, Base):
    __tablename__ = "feedback"
    __table_args__ = (Index("ix_feedback_analysis_alert", "analysis_id", "alert_id"),)

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    analysis_id = Column(Integer, ForeignKey("analyses.id", ondelete="RESTRICT"), nullable=False)
    alert_id = Column(Integer, ForeignKey("alerts.id", ondelete="RESTRICT"), nullable=True)
    submitted_by = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    clinician_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    legacy_feedback_id = Column(Integer, nullable=True, unique=True)
    alert_index = Column(Integer, nullable=True)
    legacy_alert_type = Column(String(100), nullable=True)
    legacy_drug_name = Column(String(100), nullable=True)
    alert_type = Column(String(80), nullable=True)
    feedback = enum_column(FeedbackDecision, "alert_feedback_value", nullable=True)
    rationale = Column(Text, nullable=True)
    rule_version = Column(String(80), nullable=True)
    knowledge_base_version = Column(String(80), nullable=True)
    decision = enum_column(FeedbackDecision, "feedback_decision", nullable=False, default=FeedbackDecision.UNKNOWN)
    note = Column(Text, nullable=True)
    submitted_at = Column(DateTime(timezone=True), nullable=True, server_default=func.now())


class AlertReviewAction(Base):
    __tablename__ = "alert_review_actions"
    __table_args__ = (
        Index("ix_alert_review_actions_alert_time", "alert_id", "created_at"),
        Index("ix_alert_review_actions_analysis", "analysis_id"),
    )

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    analysis_id = Column(Integer, ForeignKey("analyses.id", ondelete="RESTRICT"), nullable=False)
    alert_id = Column(Integer, ForeignKey("alerts.id", ondelete="RESTRICT"), nullable=False)
    clinician_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    action = enum_column(AlertReviewActionType, "alert_review_action", nullable=False)
    override_reason = enum_column(OverrideReason, "alert_override_reason", nullable=True)
    override_reason_text = Column(String(1000), nullable=True)
    note = Column(String(1000), nullable=True)
    rule_version = Column(String(80), nullable=True)
    knowledge_base_version = Column(String(80), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AuditEvent(Base,):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_org_time", "organization_id", "created_at"),
        Index("ix_audit_events_entity", "entity_type", "entity_id"),
    )

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=True)
    actor_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    action = Column(String(80), nullable=False)
    entity_type = Column(String(120), nullable=False)
    entity_id = Column(String(120), nullable=True)
    details = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


def _json_value(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, date):
        return value.isoformat()
    return value


@event.listens_for(Session, "before_flush")
def protect_clinical_records_and_track_allergies(session, _flush_context, _instances):
    immutable_types = (AuditEvent, AllergyChange, AnalysisRuleUsage, AlertReviewAction)
    for record in session.deleted:
        if isinstance(record, SoftDeleteMixin) or isinstance(record, immutable_types):
            raise ValueError(f"Hard deletion is disabled for {type(record).__name__}; deactivate the record instead.")
    for record in session.dirty:
        if isinstance(record, immutable_types):
            raise ValueError(f"{type(record).__name__} is append-only.")
        if isinstance(record, KnowledgeVersion):
            protected_fields = (
                "dataset", "version", "source", "source_version", "effective_date",
                "checksum", "evidence_reference", "payload",
            )
            state = inspect(record)
            if any(state.attrs[name].history.has_changes() for name in protected_fields):
                raise ValueError("KnowledgeVersion content and provenance are immutable once versioned.")

    allergy_fields = (
        "substance", "category", "reaction", "severity", "clinical_status",
        "verification_status", "onset", "notes", "source",
    )
    for allergy in tuple(session.new):
        if isinstance(allergy, Allergy):
            changed_fields = {name: {"old": None, "new": _json_value(getattr(allergy, name))} for name in allergy_fields}
            session.add(AllergyChange(
                allergy=allergy,
                change_type="CREATED",
                changed_fields=changed_fields,
                created_by=allergy.recorded_by,
            ))
    for allergy in tuple(session.dirty):
        if not isinstance(allergy, Allergy) or not session.is_modified(allergy, include_collections=False):
            continue
        state = inspect(allergy)
        changed_fields = {}
        for name in allergy_fields:
            history = state.attrs[name].history
            if history.has_changes():
                old_value = history.deleted[0] if history.deleted else None
                changed_fields[name] = {
                    "old": _json_value(old_value),
                    "new": _json_value(getattr(allergy, name)),
                }
        if changed_fields:
            session.add(AllergyChange(
                allergy=allergy,
                change_type="UPDATED",
                changed_fields=changed_fields,
                created_by=allergy.updated_by or allergy.recorded_by,
            ))
