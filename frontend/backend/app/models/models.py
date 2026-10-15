from sqlalchemy import Column, Integer, String, ForeignKey, Text, Boolean, DateTime, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base
from app.models.clinical import (
    AllergyDataStatus,
    DataStatus,
    MedicationOrderStatus,
    PregnancyStatus,
    RecordMetadata,
    SoftDeleteMixin,
    enum_column,
)

class Patient(RecordMetadata, SoftDeleteMixin, Base):
    __tablename__ = "patients"
    
    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, default=1, server_default="1")
    name = Column(String, index=True)
    age = Column(Integer)
    gender = Column(String)
    allergy_data_status = enum_column(AllergyDataStatus, "patient_allergy_data_status", nullable=False, default=AllergyDataStatus.NOT_AVAILABLE, server_default=AllergyDataStatus.NOT_AVAILABLE.value)
    renal_function_status = enum_column(DataStatus, "patient_renal_data_status", nullable=False, default=DataStatus.NOT_AVAILABLE, server_default=DataStatus.NOT_AVAILABLE.value)
    hepatic_function_status = enum_column(DataStatus, "patient_hepatic_data_status", nullable=False, default=DataStatus.NOT_AVAILABLE, server_default=DataStatus.NOT_AVAILABLE.value)
    pregnancy_status = enum_column(PregnancyStatus, "patient_pregnancy_data_status", nullable=False, default=PregnancyStatus.NOT_AVAILABLE, server_default=PregnancyStatus.NOT_AVAILABLE.value)
    
    # Relationships
    allergies = relationship("PatientAllergy", back_populates="patient", cascade="all, delete-orphan")
    conditions = relationship("PatientCondition", back_populates="patient", cascade="all, delete-orphan")
    current_meds = relationship("PatientMedication", back_populates="patient", cascade="all, delete-orphan")
    prescriptions = relationship("Prescription", back_populates="patient", cascade="all, delete-orphan")

class PatientAllergy(RecordMetadata, SoftDeleteMixin, Base):
    __tablename__ = "patient_allergies"
    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"))
    allergy_name = Column(String, index=True) # e.g., "Penicillin"
    
    patient = relationship("Patient", back_populates="allergies")

class PatientCondition(RecordMetadata, SoftDeleteMixin, Base):
    __tablename__ = "patient_conditions"
    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"))
    condition_name = Column(String, index=True) # e.g., "Hypertension"
    
    patient = relationship("Patient", back_populates="conditions")

class PatientMedication(RecordMetadata, SoftDeleteMixin, Base):
    __tablename__ = "patient_medications"
    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"))
    medication_name = Column(String, index=True) # e.g., "Warfarin"
    dose = Column(String, nullable=True) # e.g., "5mg"
    frequency = Column(String, nullable=True) # e.g., "Once daily"
    
    patient = relationship("Patient", back_populates="current_meds")

class Prescription(SoftDeleteMixin, Base):
    __tablename__ = "prescriptions"
    __table_args__ = (Index("ix_prescriptions_patient_created", "patient_id", "created_at"),)
    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, default=1, server_default="1")
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False)
    encounter_id = Column(Integer, ForeignKey("encounters.id", ondelete="RESTRICT"), nullable=True)
    raw_text = Column(Text, nullable=True) # For NLP parsing later
    created_at = Column(String, server_default=func.now()) # Legacy timestamp representation
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=func.now())
    created_by = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    updated_by = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    status = enum_column(MedicationOrderStatus, "prescription_status", nullable=False, default=MedicationOrderStatus.UNKNOWN, server_default=MedicationOrderStatus.UNKNOWN.value)
    parser_status = Column(String(32), nullable=False, default="LEGACY_IMPORTED", server_default="LEGACY_IMPORTED")
    source = Column(String(120), nullable=True)
    
    items = relationship("PrescriptionItem", back_populates="prescription", cascade="all, delete-orphan")
    orders = relationship("MedicationOrder", back_populates="prescription")
    patient = relationship("Patient", back_populates="prescriptions")

class PrescriptionItem(RecordMetadata, SoftDeleteMixin, Base):
    __tablename__ = "prescription_items"
    id = Column(Integer, primary_key=True, index=True)
    prescription_id = Column(Integer, ForeignKey("prescriptions.id"))
    drug_name = Column(String, index=True)
    dose = Column(String, nullable=True)
    unit = Column(String, nullable=True)
    frequency = Column(String, nullable=True)
    duration = Column(String, nullable=True)
    
    prescription = relationship("Prescription", back_populates="items")


class AlertFeedback(SoftDeleteMixin, Base):
    __tablename__ = "alert_feedback"
    id = Column(Integer, primary_key=True, index=True)
    analysis_id = Column(Integer, ForeignKey("prescriptions.id", ondelete="CASCADE"), index=True)
    alert_index = Column(Integer, nullable=False)
    alert_type = Column(String, nullable=True)  # e.g., "Allergy Conflict", "Drug-Drug Interaction"
    drug_name = Column(String, nullable=True)   # the primary drug involved
    override_decision = Column(Boolean, nullable=True)  # True=Agree(correct), False=Disagree(incorrect)
    clinician_note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=func.now())
    created_by = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    updated_by = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
