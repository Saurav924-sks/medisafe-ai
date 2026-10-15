from datetime import datetime, timezone
import json
import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import engine, get_db
from app.core.config import settings
from app.core.security import get_api_key, require_clinician_roles
from app.models import models
from app.models.clinical import (
    Alert,
    AlertReviewAction,
    AlertReviewActionType,
    Analysis,
    AnalysisStatus,
    AlertStatus,
    ClinicalSeverity,
    AuditEvent,
    ClinicalRule,
    DataStatus,
    Encounter,
    Feedback,
    FeedbackDecision,
    KnowledgeVersion,
    KnowledgeStatus,
    Medication,
    MedicationHistory,
    MedicationIngredient,
    MedicationOrder,
    MedicationOrderStatus,
    Observation,
    OverrideReason,
    Role,
    UserRole,
)
from app.schemas import schemas
from app.services.nlp_parser import nlp, parse_prescription_draft
from app.services.terminology import medication_terminology
from app.services.knowledge_lifecycle import validate_and_normalize
from app.services.knowledge_graph import MedicationKnowledgeGraph

# Import the AI and Safety services
from app.services.safety_engine import safety_engine
from app.services.risk_scorer import calculate_risk_score
from app.services.explainability_engine import explainability_engine
from app.interop.fhir.adapter import FHIRValidationError, normalize_bundle, validate_bundle
from app.interop.fhir.smart import smart_fhir_client

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/auth/session")
def get_authenticated_session(clinician=Depends(require_clinician_roles("ADMIN", "DOCTOR", "PHARMACIST", "CLINICAL_REVIEWER", "READ_ONLY")), db: Session = Depends(get_db)):
    roles = [name for (name,) in db.query(Role.name).join(UserRole, UserRole.role_id == Role.id).filter(UserRole.user_id == clinician.id, Role.is_active.is_(True)).all()]
    return {"clinician_id": clinician.id, "display_name": clinician.display_name, "roles": roles}

def _normalization_outcome(medication_name: str, knowledge_data: dict | None = None) -> dict:
    return medication_terminology.normalize(medication_name, knowledge_data=knowledge_data).as_dict()

def _prescription_order_response(order: MedicationOrder) -> dict:
    normalized = order.normalization_result or {}
    return {
        "id": order.id,
        "medication_name": order.medication_name_snapshot,
        "dose": order.dose,
        "unit": order.unit,
        "route": order.route,
        "frequency": order.frequency,
        "duration": order.duration,
        "indication": order.indication,
        "status": order.status.value if hasattr(order.status, "value") else order.status,
        "normalization_status": order.normalization_status,
        "normalization_confidence": float(order.normalization_confidence) if order.normalization_confidence is not None else None,
        "match_method": order.match_method,
        "normalization_message": order.normalization_message,
        "canonical_entity": normalized.get("canonical_entity"),
        "normalization_confirmed": bool(normalized.get("clinician_confirmed_by")),
        "clinician_review_required": order.status != MedicationOrderStatus.ACTIVE,
    }

def _prescription_response(prescription: models.Prescription) -> dict:
    return {
        "id": prescription.id,
        "patient_id": prescription.patient_id,
        "status": prescription.status.value if hasattr(prescription.status, "value") else prescription.status,
        "parser_status": prescription.parser_status,
        "raw_text": prescription.raw_text,
        "created_at": prescription.created_at,
        "clinician_review_required": prescription.status != MedicationOrderStatus.ACTIVE,
        "orders": [_prescription_order_response(order) for order in prescription.orders],
    }

def _local_catalog_record(db: Session, canonical_entity: dict) -> Medication:
    normalized_name = " ".join(canonical_entity["name"].casefold().split())
    medication = db.query(Medication).filter(Medication.normalized_name == normalized_name).first()
    if medication:
        return medication

    strength = canonical_entity.get("strength") or {}
    ingredient = (canonical_entity.get("ingredients") or [{}])[0]
    medication = Medication(
        name=canonical_entity["name"],
        normalized_name=normalized_name,
        code=canonical_entity.get("concept_id"),
        code_system=canonical_entity.get("code_system"),
        strength_value=strength.get("value"),
        strength_unit=strength.get("unit"),
        dose_form=canonical_entity.get("dose_form"),
        route=canonical_entity.get("route"),
        catalog_status=DataStatus.KNOWN,
        source=canonical_entity.get("source"),
    )
    db.add(medication)
    db.flush()

    if ingredient.get("name"):
        db.add(MedicationIngredient(
            medication_id=medication.id,
            name=ingredient["name"],
            normalized_name=" ".join(ingredient["name"].casefold().split()),
            code=ingredient.get("concept_id"),
            code_system=canonical_entity.get("code_system"),
            source=canonical_entity.get("source"),
        ))
    return medication

@router.post("/prescriptions", response_model=schemas.PrescriptionResponse)
def create_prescription(
    prescription: schemas.PrescriptionCreateRequest,
    db: Session = Depends(get_db),
    clinician=Depends(require_clinician_roles("ADMIN", "DOCTOR", "PHARMACIST", "CLINICAL_REVIEWER")),
):
    patient = db.query(models.Patient).filter(models.Patient.id == prescription.patient_id).first()
    if patient is None or patient.organization_id != clinician.organization_id:
        raise HTTPException(status_code=404, detail="Patient not found")
    knowledge_version = _active_knowledge_version(db)

    if prescription.medication_orders:
        proposed_orders = [item.model_dump() for item in prescription.medication_orders]
        parser_status = "STRUCTURED_DRAFT"
        source = "MANUAL_STRUCTURED_DRAFT"
    else:
        parsed = parse_prescription_draft(prescription.raw_text or "", knowledge_data=knowledge_version.payload)
        proposed_orders = parsed["orders"]
        parser_status = parsed["status"]
        source = "NATURAL_LANGUAGE_DRAFT"

    db_prescription = models.Prescription(
        organization_id=patient.organization_id,
        patient_id=patient.id,
        raw_text=prescription.raw_text,
        status=MedicationOrderStatus.DRAFT,
        parser_status=parser_status,
        source=source,
    )
    db.add(db_prescription)
    db.flush()

    for proposed in proposed_orders:
        medication_name = proposed["medication_name"]
        outcome = _normalization_outcome(medication_name, knowledge_data=knowledge_version.payload)
        medication_id = None
        canonical_entity = outcome["canonical_entity"]
        if outcome["status"] == "NORMALIZED" and canonical_entity is not None:
            medication_id = _local_catalog_record(db, canonical_entity).id

        dose = proposed.get("dose")
        if dose is not None:
            dose = str(dose)
        unit = proposed.get("unit")
        if unit:
            unit = {"MG": "mg", "MCG": "mcg", "G": "g", "ML": "mL"}.get(unit.upper(), unit)

        order = MedicationOrder(
            organization_id=patient.organization_id,
            patient_id=patient.id,
            prescription_id=db_prescription.id,
            medication_id=medication_id,
            medication_name_snapshot=medication_name,
            dose=dose,
            unit=unit,
            route=(proposed["route"].value if hasattr(proposed.get("route"), "value") else proposed.get("route")),
            frequency=proposed.get("frequency"),
            duration=proposed.get("duration"),
            indication=proposed.get("indication"),
            status=MedicationOrderStatus.DRAFT,
            source=source,
            normalization_status=outcome["status"],
            normalization_confidence=outcome["confidence"],
            match_method=outcome["match_method"],
            normalization_message=outcome["message"],
            normalization_result=outcome,
        )
        db.add(order)
        db.flush()

        db.add(AuditEvent(
            organization_id=patient.organization_id,
            action="MEDICATION_NORMALIZATION_OUTCOME",
            entity_type="MedicationOrder",
            entity_id=str(order.id),
            details={
                "prescription_id": db_prescription.id,
                "status": outcome["status"],
                "confidence": outcome["confidence"],
                "match_method": outcome["match_method"],
                "provider": outcome["provider"],
            },
        ))

    db.add(AuditEvent(
        organization_id=patient.organization_id,
        action="PRESCRIPTION_CREATED",
        entity_type="Prescription",
        entity_id=str(db_prescription.id),
        details={
            "patient_id": patient.id,
            "parser_status": parser_status,
            "order_count": len(proposed_orders),
            "source": source,
        },
    ))
    db.commit()
    db.refresh(db_prescription)
    return _prescription_response(db_prescription)

@router.get("/prescriptions/{prescription_id}", response_model=schemas.PrescriptionResponse)
def get_prescription(
    prescription_id: int,
    db: Session = Depends(get_db),
    clinician=Depends(require_clinician_roles("ADMIN", "DOCTOR", "PHARMACIST", "CLINICAL_REVIEWER", "READ_ONLY")),
):
    prescription = (
        db.query(models.Prescription)
        .filter(models.Prescription.id == prescription_id)
        .first()
    )
    if prescription is None:
        raise HTTPException(status_code=404, detail="Prescription not found")
    if prescription.organization_id != clinician.organization_id:
        raise HTTPException(status_code=404, detail="Prescription not found")
    return _prescription_response(prescription)


@router.post("/prescriptions/{prescription_id}/confirm-normalization")
def confirm_prescription_normalization(
    prescription_id: int,
    db: Session = Depends(get_db),
    clinician=Depends(require_clinician_roles("ADMIN", "DOCTOR", "PHARMACIST", "CLINICAL_REVIEWER")),
):
    prescription = db.query(models.Prescription).filter(models.Prescription.id == prescription_id).first()
    if prescription is None:
        raise HTTPException(status_code=404, detail="Prescription not found")
    if prescription.organization_id != clinician.organization_id:
        raise HTTPException(status_code=404, detail="Prescription not found")
    patient = db.query(models.Patient).filter(models.Patient.id == prescription.patient_id, models.Patient.organization_id == clinician.organization_id).first()
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    if not prescription.orders:
        raise HTTPException(status_code=409, detail="Prescription has no structured medication orders to confirm.")
    unnormalized = [order.id for order in prescription.orders if order.normalization_status != "NORMALIZED"]
    if unnormalized:
        raise HTTPException(status_code=409, detail={"message": "Medication could not be confidently normalized; resolve each item before confirmation.", "order_ids": unnormalized})
    confirmed_at = datetime.now(timezone.utc).isoformat()
    for order in prescription.orders:
        order.normalization_result = {**(order.normalization_result or {}), "clinician_confirmed_by": clinician.id, "clinician_confirmed_at": confirmed_at}
    db.add(AuditEvent(organization_id=patient.organization_id, actor_id=clinician.id, action="PRESCRIPTION_NORMALIZATION_CONFIRMED", entity_type="Prescription", entity_id=str(prescription.id), details={"order_ids": [order.id for order in prescription.orders]}))
    db.commit()
    return {"prescription_id": prescription.id, "confirmed_order_ids": [order.id for order in prescription.orders], "confirmed_at": confirmed_at}


@router.post("/prescriptions/{prescription_id}/analyze")
def analyze_structured_prescription(
    prescription_id: int,
    db: Session = Depends(get_db),
    clinician=Depends(require_clinician_roles("ADMIN", "DOCTOR", "PHARMACIST", "CLINICAL_REVIEWER")),
):
    prescription = db.query(models.Prescription).filter(models.Prescription.id == prescription_id).first()
    if prescription is None:
        raise HTTPException(status_code=404, detail="Prescription not found")
    patient = db.query(models.Patient).filter(models.Patient.id == prescription.patient_id, models.Patient.organization_id == clinician.organization_id).first()
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    if not prescription.orders or any(order.normalization_status != "NORMALIZED" or not (order.normalization_result or {}).get("clinician_confirmed_by") for order in prescription.orders):
        raise HTTPException(status_code=409, detail="Confirm all confidently normalized medication orders before analysis.")
    knowledge_version = _active_knowledge_version(db)
    patient_profile = {
        "allergies": [{"allergy_name": item.allergy_name} for item in patient.allergies],
        "conditions": [{"condition_name": item.condition_name} for item in patient.conditions],
        "current_medications": [{"medication_name": item.medication_name} for item in patient.current_meds],
    }
    proposed = [{"drug_name": order.normalization_result["canonical_entity"]["name"], "dose": order.dose, "unit": order.unit, "frequency": order.frequency, "duration": order.duration} for order in prescription.orders]
    raw_alerts = safety_engine.analyze(patient_profile, proposed, knowledge_graph=MedicationKnowledgeGraph(data=knowledge_version.payload))
    severity_order = {"CRITICAL": 0, "HIGH": 1, "MODERATE": 2, "LOW": 3, "INFORMATIONAL": 4, "UNKNOWN": 5}
    raw_alerts.sort(key=lambda item: severity_order.get(item.get("severity", "UNKNOWN"), 5))
    explained = explainability_engine.generate_explanations(raw_alerts, patient_profile, proposed, knowledge_version.payload)
    analysis = Analysis(
        organization_id=patient.organization_id, patient_id=patient.id, prescription_id=prescription.id,
        knowledge_version_id=knowledge_version.id,
        rule_set_version=f"{knowledge_version.dataset}:{knowledge_version.version}",
        status=AnalysisStatus.PARTIALLY_EVALUATED,
        allergy_checked=True, drug_drug_checked=True, drug_disease_checked=True,
        dose_checked=True, duplicate_therapy_checked=True,
        other_domains={"renal": "NOT_EVALUATED", "hepatic": "NOT_EVALUATED", "pregnancy": "NOT_EVALUATED", "age": "NOT_EVALUATED"},
    )
    db.add(analysis)
    db.flush()
    output_alerts = []
    for index, item in enumerate(explained):
        raw = raw_alerts[index]
        severity_name = str(raw.get("severity", "UNKNOWN")).upper()
        try:
            severity = ClinicalSeverity(severity_name)
        except ValueError:
            severity = ClinicalSeverity.UNKNOWN
        record = Alert(
            organization_id=patient.organization_id, analysis_id=analysis.id, alert_index=index,
            domain=raw.get("type", "UNKNOWN"), severity=severity, status=AlertStatus.OPEN,
            message=item.get("what_detected") or item.get("why_flagged") or "Insufficient data to evaluate",
            evidence_reference=item.get("evidence"), source=item.get("source"), recommendation=item.get("recommended_action"),
            details={**item, "rule_id": raw.get("rule_id"), "rule_version": analysis.rule_set_version},
        )
        db.add(record)
        db.flush()
        output_alerts.append({"id": record.id, **item, "type": raw.get("type"), "rule_id": raw.get("rule_id"), "rule_version": analysis.rule_set_version})
    db.add(AuditEvent(organization_id=patient.organization_id, actor_id=clinician.id, action="PRESCRIPTION_ANALYSIS_COMPLETED", entity_type="Analysis", entity_id=str(analysis.id), details={"prescription_id": prescription.id, "knowledge_version": knowledge_version.version, "rule_set_version": analysis.rule_set_version, "status": analysis.status.value, "alert_count": len(output_alerts)}))
    db.commit()
    return {
        "id": analysis.id, "prescription_id": prescription.id, "analysis_status": analysis.status.value,
        "knowledge_version": knowledge_version.version, "rule_set_version": analysis.rule_set_version,
        "safety_domains": {"allergy": "EVALUATED", "drug_drug": "EVALUATED", "drug_disease": "EVALUATED", "dose": "EVALUATED", "duplicate_therapy": "EVALUATED", "renal": "NOT_EVALUATED", "hepatic": "NOT_EVALUATED", "pregnancy": "NOT_EVALUATED", "age": "NOT_EVALUATED"},
        "data_quality": {"patient_source": "legacy_patient_record", "freshness": "NOT_AVAILABLE", "allergy_verification": "UNKNOWN", "medication_history": "NOT_AVAILABLE"},
        "alerts": output_alerts, "total_alerts": len(output_alerts),
        "disclaimer": risk_result["disclaimer"] if (risk_result := calculate_risk_score(raw_alerts, knowledge_version.payload.get("priority_scoring"))) else None,
    }


def _alert_version_context(db: Session, alert: Alert) -> tuple[Analysis, str | None, str | None]:
    analysis = db.query(Analysis).filter(Analysis.id == alert.analysis_id).first()
    if analysis is None:
        raise HTTPException(status_code=404, detail="Alert analysis not found")
    rule = db.query(ClinicalRule).filter(ClinicalRule.id == alert.clinical_rule_id).first() if alert.clinical_rule_id else None
    knowledge = (
        db.query(KnowledgeVersion).filter(KnowledgeVersion.id == analysis.knowledge_version_id).first()
        if analysis.knowledge_version_id else None
    )
    # Some imported/legacy alerts do not point at an individual ClinicalRule.
    # Preserve the version captured by their analysis instead of losing the
    # provenance on review actions, feedback, and audit events.
    rule_version = rule.version if rule else analysis.rule_set_version
    return analysis, rule_version, knowledge.version if knowledge else None


def _alert_type(alert: Alert) -> str:
    if isinstance(alert.details, dict):
        alert_type = alert.details.get("type")
        if isinstance(alert_type, str) and alert_type.strip():
            return alert_type.strip()
    return alert.domain


def _active_knowledge_version(db: Session) -> KnowledgeVersion:
    version = db.query(KnowledgeVersion).filter(
        KnowledgeVersion.dataset == "medisafe-clinical",
        KnowledgeVersion.lifecycle_stage == "ACTIVE",
    ).first()
    if version is None or not isinstance(version.payload, dict):
        raise HTTPException(status_code=503, detail="No clinically reviewed knowledge version is active; analysis is incomplete.")
    return version


def _knowledge_audit(db: Session, organization_id: int | None, actor_id: int, action: str, version: KnowledgeVersion, details: dict | None = None) -> None:
    db.add(AuditEvent(
        organization_id=organization_id,
        actor_id=actor_id,
        action=action,
        entity_type="KnowledgeVersion",
        entity_id=str(version.id),
        details={
            "dataset": version.dataset,
            "version": version.version,
            "checksum": version.checksum,
            **(details or {}),
        },
    ))


@router.get("/knowledge/versions")
def list_knowledge_versions(
    db: Session = Depends(get_db),
    clinician=Depends(require_clinician_roles("ADMIN", "CLINICAL_REVIEWER", "READ_ONLY")),
):
    versions = db.query(KnowledgeVersion).order_by(KnowledgeVersion.dataset, KnowledgeVersion.id).all()
    return [{
        "id": version.id,
        "dataset": version.dataset,
        "version": version.version,
        "source": version.source,
        "source_version": version.source_version,
        "effective_date": version.effective_date.isoformat() if version.effective_date else None,
        "last_reviewed": version.last_reviewed.isoformat() if version.last_reviewed else None,
        "evidence_reference": version.evidence_reference,
        "checksum": version.checksum,
        "lifecycle_stage": version.lifecycle_stage,
        "review_note": version.review_note,
    } for version in versions]


@router.get("/knowledge/active")
def get_active_knowledge(
    db: Session = Depends(get_db),
    clinician=Depends(require_clinician_roles("ADMIN", "DOCTOR", "PHARMACIST", "CLINICAL_REVIEWER", "READ_ONLY")),
):
    version = _active_knowledge_version(db)
    return {
        "id": version.id,
        "dataset": version.dataset,
        "version": version.version,
        "checksum": version.checksum,
        "source": version.source,
        "source_version": version.source_version,
        "effective_date": version.effective_date.isoformat() if version.effective_date else None,
        "last_reviewed": version.last_reviewed.isoformat() if version.last_reviewed else None,
        "evidence_reference": version.evidence_reference,
        "activated_at": version.activated_at.isoformat() if version.activated_at else None,
    }


@router.post("/knowledge/import")
async def import_knowledge_file(
    request: Request,
    db: Session = Depends(get_db),
    clinician=Depends(require_clinician_roles("ADMIN", "CLINICAL_REVIEWER")),
):
    """Import a JSON knowledge file; network retrieval is deliberately unsupported."""
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise HTTPException(status_code=415, detail="Knowledge imports must be uploaded as a JSON file.")
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 5 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Knowledge file must be no larger than 5 MB.")
    if not raw:
        raise HTTPException(status_code=422, detail="Knowledge file must be non-empty.")
    try:
        document = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail="Knowledge import must be a UTF-8 JSON file.") from exc
    manifest, payload, digest = validate_and_normalize(document)
    duplicate = db.query(KnowledgeVersion).filter(
        KnowledgeVersion.dataset == manifest["dataset"],
        KnowledgeVersion.version == manifest["version"],
    ).first()
    if duplicate:
        raise HTTPException(status_code=409, detail="Knowledge dataset version already exists; versions are immutable.")

    version = KnowledgeVersion(
        dataset=manifest["dataset"],
        version=manifest["version"],
        source=manifest["source"],
        source_version=manifest["source_version"],
        effective_date=datetime.fromisoformat(manifest["effective_date"]).date() if manifest["effective_date"] else None,
        last_reviewed=datetime.fromisoformat(manifest["last_reviewed"]).date() if manifest["last_reviewed"] else None,
        checksum=digest,
        evidence_reference=manifest["evidence_reference"],
        review_note=manifest.get("review_note"),
        payload=payload,
        status=KnowledgeStatus.LOADED,
        lifecycle_stage="REVIEW_PENDING",
    )
    db.add(version)
    db.flush()
    for stage in ("IMPORTED", "VALIDATED", "NORMALIZED", "VERSIONED"):
        _knowledge_audit(db, clinician.organization_id, clinician.id, f"KNOWLEDGE_{stage}", version)
    db.commit()
    db.refresh(version)
    return {"id": version.id, "dataset": version.dataset, "version": version.version,
            "checksum": version.checksum, "lifecycle_stage": version.lifecycle_stage}


@router.post("/knowledge/{version_id}/review")
def review_knowledge_version(
    version_id: int,
    request: schemas.KnowledgeReviewRequest,
    db: Session = Depends(get_db),
    clinician=Depends(require_clinician_roles("ADMIN", "CLINICAL_REVIEWER")),
):
    version = db.query(KnowledgeVersion).filter(KnowledgeVersion.id == version_id).first()
    if version is None:
        raise HTTPException(status_code=404, detail="Knowledge version not found")
    if version.lifecycle_stage != "REVIEW_PENDING":
        raise HTTPException(status_code=409, detail="Only pending knowledge versions can be clinically reviewed.")
    version.lifecycle_stage = "CLINICALLY_REVIEWED"
    version.reviewed_by = clinician.id
    version.last_reviewed = datetime.now(timezone.utc).date()
    version.review_note = request.review_note.strip()
    _knowledge_audit(db, clinician.organization_id, clinician.id, "KNOWLEDGE_CLINICALLY_REVIEWED", version)
    db.commit()
    return {"id": version.id, "version": version.version, "lifecycle_stage": version.lifecycle_stage,
            "reviewed_by": version.reviewed_by, "last_reviewed": version.last_reviewed.isoformat()}


def _activate_knowledge_version(db: Session, clinician, target: KnowledgeVersion, expected_active_version_id: int | None, action: str) -> dict:
    active = db.query(KnowledgeVersion).filter(
        KnowledgeVersion.dataset == target.dataset,
        KnowledgeVersion.lifecycle_stage == "ACTIVE",
    ).first()
    actual_active_id = active.id if active else None
    if actual_active_id != expected_active_version_id:
        raise HTTPException(status_code=409, detail="Active knowledge version changed; reload and explicitly confirm the expected version.")
    allowed_target_stages = {"CLINICALLY_REVIEWED", "SUPERSEDED"} if action == "KNOWLEDGE_ROLLED_BACK" else {"CLINICALLY_REVIEWED"}
    if target.lifecycle_stage not in allowed_target_stages or target.reviewed_by is None or target.last_reviewed is None:
        raise HTTPException(status_code=409, detail="Knowledge must have a recorded clinical reviewer sign-off before activation.")
    if active and active.id == target.id:
        raise HTTPException(status_code=409, detail="Knowledge version is already active.")
    if active:
        active.lifecycle_stage = "SUPERSEDED"
        db.flush()
    target.lifecycle_stage = "ACTIVE"
    target.activated_by = clinician.id
    target.activated_at = datetime.now(timezone.utc)
    _knowledge_audit(db, clinician.organization_id, clinician.id, action, target,
                     {"previous_active_version_id": actual_active_id})
    db.commit()
    return {"id": target.id, "dataset": target.dataset, "version": target.version,
            "lifecycle_stage": target.lifecycle_stage, "previous_active_version_id": actual_active_id}


@router.post("/knowledge/{version_id}/activate")
def activate_knowledge_version(
    version_id: int,
    request: schemas.KnowledgeActivationRequest,
    db: Session = Depends(get_db),
    clinician=Depends(require_clinician_roles("ADMIN", "CLINICAL_REVIEWER")),
):
    target = db.query(KnowledgeVersion).filter(KnowledgeVersion.id == version_id).first()
    if target is None:
        raise HTTPException(status_code=404, detail="Knowledge version not found")
    return _activate_knowledge_version(db, clinician, target, request.expected_active_version_id, "KNOWLEDGE_ACTIVATED")


@router.post("/knowledge/{version_id}/rollback")
def rollback_knowledge_version(
    version_id: int,
    request: schemas.KnowledgeActivationRequest,
    db: Session = Depends(get_db),
    clinician=Depends(require_clinician_roles("ADMIN", "CLINICAL_REVIEWER")),
):
    target = db.query(KnowledgeVersion).filter(KnowledgeVersion.id == version_id).first()
    if target is None:
        raise HTTPException(status_code=404, detail="Knowledge version not found")
    return _activate_knowledge_version(db, clinician, target, request.expected_active_version_id, "KNOWLEDGE_ROLLED_BACK")


@router.post("/alerts/{alert_id}/actions")
def record_alert_action(
    alert_id: int,
    request: schemas.AlertReviewActionCreate,
    db: Session = Depends(get_db),
    clinician=Depends(require_clinician_roles("ADMIN", "DOCTOR", "PHARMACIST", "CLINICAL_REVIEWER")),
):
    permitted_roles = {
        AlertReviewActionType.REVIEW: {"ADMIN", "DOCTOR", "PHARMACIST", "CLINICAL_REVIEWER"},
        AlertReviewActionType.ACKNOWLEDGE: {"ADMIN", "DOCTOR", "PHARMACIST", "CLINICAL_REVIEWER"},
        AlertReviewActionType.OVERRIDE: {"ADMIN", "DOCTOR", "CLINICAL_REVIEWER"},
        AlertReviewActionType.RESOLVE: {"ADMIN", "DOCTOR", "CLINICAL_REVIEWER"},
        AlertReviewActionType.DISMISS: {"ADMIN", "DOCTOR", "CLINICAL_REVIEWER"},
    }
    clinician_roles = {
        role_name
        for (role_name,) in (
            db.query(Role.name)
            .join(UserRole, UserRole.role_id == Role.id)
            .filter(UserRole.user_id == clinician.id)
            .all()
        )
    }
    if not clinician_roles.intersection(permitted_roles[AlertReviewActionType(request.action.value)]):
        raise HTTPException(status_code=403, detail="Clinician role is not permitted for this alert action.")

    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if alert is None or alert.organization_id != clinician.organization_id:
        raise HTTPException(status_code=404, detail="Alert not found")
    analysis, rule_version, knowledge_version = _alert_version_context(db, alert)

    action = AlertReviewActionType(request.action.value)
    severity = alert.severity.value if hasattr(alert.severity, "value") else str(alert.severity)
    if action == AlertReviewActionType.OVERRIDE and severity in {"HIGH", "CRITICAL"} and request.override_reason is None:
        raise HTTPException(
            status_code=422,
            detail="A structured override reason is required for HIGH or CRITICAL alerts.",
        )
    if action != AlertReviewActionType.OVERRIDE and request.override_reason is not None:
        raise HTTPException(status_code=422, detail="override_reason is only valid for OVERRIDE actions.")

    action_record = AlertReviewAction(
        organization_id=alert.organization_id,
        analysis_id=analysis.id,
        alert_id=alert.id,
        clinician_id=clinician.id,
        action=action,
        override_reason=OverrideReason(request.override_reason.value) if request.override_reason else None,
        override_reason_text=request.override_reason_text,
        note=request.note,
        rule_version=rule_version,
        knowledge_base_version=knowledge_version,
    )
    db.add(action_record)
    db.flush()
    db.add(AuditEvent(
        organization_id=alert.organization_id,
        actor_id=clinician.id,
        action=f"ALERT_{action.value}",
        entity_type="Alert",
        entity_id=str(alert.id),
        details={
            "analysis_id": analysis.id,
            "review_action_id": action_record.id,
            "action": action.value,
            "rule_version": rule_version,
            "knowledge_base_version": knowledge_version,
            "override_reason": request.override_reason.value if request.override_reason else None,
        },
    ))
    db.commit()
    db.refresh(action_record)
    return {
        "id": action_record.id,
        "analysis_id": action_record.analysis_id,
        "alert_id": action_record.alert_id,
        "clinician_id": action_record.clinician_id,
        "action": action_record.action.value,
        "override_reason": action_record.override_reason.value if action_record.override_reason else None,
        "override_reason_text": action_record.override_reason_text,
        "rule_version": action_record.rule_version,
        "knowledge_base_version": action_record.knowledge_base_version,
        "created_at": action_record.created_at.isoformat(),
    }


@router.post("/alerts/{alert_id}/feedback")
def record_alert_feedback(
    alert_id: int,
    request: schemas.AlertFeedbackCreate,
    db: Session = Depends(get_db),
    clinician=Depends(require_clinician_roles("ADMIN", "DOCTOR", "PHARMACIST", "CLINICAL_REVIEWER")),
):
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if alert is None or alert.organization_id != clinician.organization_id:
        raise HTTPException(status_code=404, detail="Alert not found")
    analysis, rule_version, knowledge_version = _alert_version_context(db, alert)
    if analysis.id != request.analysis_id:
        raise HTTPException(status_code=422, detail="analysis_id does not match the alert.")

    feedback_value = FeedbackDecision(request.feedback.value)
    feedback_record = Feedback(
        organization_id=alert.organization_id,
        analysis_id=analysis.id,
        alert_id=alert.id,
        submitted_by=clinician.id,
        clinician_id=clinician.id,
        alert_type=_alert_type(alert),
        feedback=feedback_value,
        decision=feedback_value,
        rationale=request.rationale,
        note=request.rationale,
        rule_version=rule_version,
        knowledge_base_version=knowledge_version,
    )
    db.add(feedback_record)
    db.flush()
    db.add(AuditEvent(
        organization_id=alert.organization_id,
        actor_id=clinician.id,
        action="ALERT_FEEDBACK_RECORDED",
        entity_type="Alert",
        entity_id=str(alert.id),
        details={
            "analysis_id": analysis.id,
            "feedback_id": feedback_record.id,
            "alert_type": feedback_record.alert_type,
            "feedback": feedback_value.value,
            "rule_version": rule_version,
            "knowledge_base_version": knowledge_version,
        },
    ))
    db.commit()
    return {
        "id": feedback_record.id,
        "analysis_id": analysis.id,
        "alert_id": alert.id,
        "alert_type": feedback_record.alert_type,
        "clinician_id": clinician.id,
        "feedback": feedback_value.value,
        "rule_version": rule_version,
        "knowledge_base_version": knowledge_version,
        "submitted_at": feedback_record.submitted_at.isoformat() if feedback_record.submitted_at else None,
    }


@router.get("/alerts/review-queue")
def get_alert_review_queue(
    db: Session = Depends(get_db),
    clinician=Depends(require_clinician_roles("ADMIN", "DOCTOR", "PHARMACIST", "CLINICAL_REVIEWER", "READ_ONLY")),
):
    final_actions = db.query(AlertReviewAction.alert_id).filter(
        AlertReviewAction.action.in_([
            AlertReviewActionType.OVERRIDE,
            AlertReviewActionType.RESOLVE,
            AlertReviewActionType.DISMISS,
        ])
    )
    alerts = (
        db.query(Alert)
        .filter(Alert.organization_id == clinician.organization_id, ~Alert.id.in_(final_actions))
        .order_by(Alert.created_at.asc())
        .limit(100)
        .all()
    )
    queue = []
    for alert in alerts:
        latest_action = (
            db.query(AlertReviewAction)
            .filter(AlertReviewAction.alert_id == alert.id)
            .order_by(AlertReviewAction.id.desc())
            .first()
        )
        queue.append({
            "alert_id": alert.id,
            "analysis_id": alert.analysis_id,
            "domain": alert.domain,
            "severity": alert.severity.value if hasattr(alert.severity, "value") else alert.severity,
            "message": alert.message,
            "status": alert.status.value if hasattr(alert.status, "value") else alert.status,
            "last_action": latest_action.action.value if latest_action else None,
            "rule_version": _alert_version_context(db, alert)[1],
        })
    return queue

# --- Patient Routes ---

@router.post("/patients", response_model=schemas.PatientResponse)
def create_patient(patient: schemas.PatientCreate, db: Session = Depends(get_db), clinician=Depends(require_clinician_roles("ADMIN", "DOCTOR", "PHARMACIST"))):
    db_patient = models.Patient(
        **patient.model_dump(),
        organization_id=clinician.organization_id,
    )
    db.add(db_patient)
    db.commit()
    db.refresh(db_patient)
    return db_patient

@router.get("/patients", response_model=List[schemas.PatientResponse])
def list_patients(db: Session = Depends(get_db), clinician=Depends(require_clinician_roles("ADMIN", "DOCTOR", "PHARMACIST", "CLINICAL_REVIEWER", "READ_ONLY"))):
    return db.query(models.Patient).filter(models.Patient.organization_id == clinician.organization_id).all()

@router.get("/patients/{patient_id}", response_model=schemas.PatientResponse)
def get_patient(patient_id: int, db: Session = Depends(get_db), clinician=Depends(require_clinician_roles("ADMIN", "DOCTOR", "PHARMACIST", "CLINICAL_REVIEWER", "READ_ONLY"))):
    patient = db.query(models.Patient).filter(models.Patient.id == patient_id, models.Patient.organization_id == clinician.organization_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    return patient


def _get_scoped_patient(patient_id: int, organization_id: int, db: Session) -> models.Patient:
    patient = (
        db.query(models.Patient)
        .filter(
            models.Patient.id == patient_id,
            models.Patient.organization_id == organization_id,
        )
        .first()
    )
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    return patient


@router.get("/patients/{patient_id}/medication-history")
def get_patient_medication_history(
    patient_id: int,
    db: Session = Depends(get_db),
    clinician=Depends(require_clinician_roles("ADMIN", "DOCTOR", "PHARMACIST", "CLINICAL_REVIEWER", "READ_ONLY")),
):
    patient = _get_scoped_patient(patient_id, clinician.organization_id, db)
    records = (
        db.query(MedicationHistory)
        .filter(
            MedicationHistory.patient_id == patient.id,
            MedicationHistory.organization_id == clinician.organization_id,
        )
        .order_by(MedicationHistory.started_at.desc(), MedicationHistory.id.desc())
        .all()
    )
    return [{
        "id": record.id,
        "patient_id": record.patient_id,
        "medication_id": record.medication_id,
        "medication_name": record.medication_name_snapshot,
        "dose": record.dose,
        "frequency": record.frequency,
        "indication": record.indication,
        "status": record.status.value if hasattr(record.status, "value") else record.status,
        "source": record.source,
        "started_at": record.started_at,
        "ended_at": record.ended_at,
        "last_verified_at": record.last_verified_at,
    } for record in records]


@router.get("/patients/{patient_id}/observations")
def get_patient_observations(
    patient_id: int,
    db: Session = Depends(get_db),
    clinician=Depends(require_clinician_roles("ADMIN", "DOCTOR", "PHARMACIST", "CLINICAL_REVIEWER", "READ_ONLY")),
):
    patient = _get_scoped_patient(patient_id, clinician.organization_id, db)
    records = (
        db.query(Observation)
        .filter(
            Observation.patient_id == patient.id,
            Observation.organization_id == clinician.organization_id,
        )
        .order_by(Observation.observed_at.desc(), Observation.id.desc())
        .all()
    )
    return [{
        "id": record.id,
        "patient_id": record.patient_id,
        "encounter_id": record.encounter_id,
        "code": record.code,
        "code_system": record.code_system,
        "availability_status": record.availability_status.value if hasattr(record.availability_status, "value") else record.availability_status,
        "value_number": record.value_number,
        "value_text": record.value_text,
        "unit": record.unit,
        "observed_at": record.observed_at,
        "source": record.source,
    } for record in records]


@router.get("/patients/{patient_id}/encounters")
def get_patient_encounters(
    patient_id: int,
    db: Session = Depends(get_db),
    clinician=Depends(require_clinician_roles("ADMIN", "DOCTOR", "PHARMACIST", "CLINICAL_REVIEWER", "READ_ONLY")),
):
    patient = _get_scoped_patient(patient_id, clinician.organization_id, db)
    records = (
        db.query(Encounter)
        .filter(
            Encounter.patient_id == patient.id,
            Encounter.organization_id == clinician.organization_id,
        )
        .order_by(Encounter.started_at.desc(), Encounter.id.desc())
        .all()
    )
    return [{
        "id": record.id,
        "patient_id": record.patient_id,
        "external_id": record.external_id,
        "encounter_type": record.encounter_type,
        "status": record.status,
        "started_at": record.started_at,
        "ended_at": record.ended_at,
        "source": record.source,
    } for record in records]


@router.get("/patients/{patient_id}/prescriptions")
def get_patient_prescriptions(
    patient_id: int,
    db: Session = Depends(get_db),
    clinician=Depends(require_clinician_roles("ADMIN", "DOCTOR", "PHARMACIST", "CLINICAL_REVIEWER", "READ_ONLY")),
):
    patient = _get_scoped_patient(patient_id, clinician.organization_id, db)
    prescriptions = (
        db.query(models.Prescription)
        .filter(
            models.Prescription.patient_id == patient.id,
            models.Prescription.organization_id == clinician.organization_id,
        )
        .order_by(models.Prescription.created_at.desc(), models.Prescription.id.desc())
        .all()
    )
    return [_prescription_response(prescription) for prescription in prescriptions]

@router.post("/patients/{patient_id}/allergies")
def add_allergy(patient_id: int, allergy: schemas.AllergyCreate, db: Session = Depends(get_db), clinician=Depends(require_clinician_roles("ADMIN", "DOCTOR", "PHARMACIST"))):
    if not db.query(models.Patient).filter(models.Patient.id == patient_id, models.Patient.organization_id == clinician.organization_id).first():
        raise HTTPException(status_code=404, detail="Patient not found")
    db_allergy = models.PatientAllergy(patient_id=patient_id, **allergy.model_dump())
    db.add(db_allergy)
    db.commit()
    db.refresh(db_allergy)
    return {"message": "Allergy added", "data": db_allergy}

@router.post("/patients/{patient_id}/conditions")
def add_condition(patient_id: int, condition: schemas.ConditionCreate, db: Session = Depends(get_db), clinician=Depends(require_clinician_roles("ADMIN", "DOCTOR", "PHARMACIST"))):
    if not db.query(models.Patient).filter(models.Patient.id == patient_id, models.Patient.organization_id == clinician.organization_id).first():
        raise HTTPException(status_code=404, detail="Patient not found")
    db_condition = models.PatientCondition(patient_id=patient_id, **condition.model_dump())
    db.add(db_condition)
    db.commit()
    db.refresh(db_condition)
    return {"message": "Condition added", "data": db_condition}

@router.post("/patients/{patient_id}/medications")
def add_medication(patient_id: int, med: schemas.MedicationCreate, db: Session = Depends(get_db), clinician=Depends(require_clinician_roles("ADMIN", "DOCTOR", "PHARMACIST"))):
    if not db.query(models.Patient).filter(models.Patient.id == patient_id, models.Patient.organization_id == clinician.organization_id).first():
        raise HTTPException(status_code=404, detail="Patient not found")
    db_med = models.PatientMedication(patient_id=patient_id, **med.model_dump())
    db.add(db_med)
    db.commit()
    db.refresh(db_med)
    return {"message": "Medication added", "data": db_med}

# --- Prescription Analysis Route (WIRED) ---

@router.post("/prescriptions/analyze")
def analyze_prescription(
    prescription: schemas.PrescriptionCreate,
    db: Session = Depends(get_db),
    clinician=Depends(require_clinician_roles("ADMIN", "DOCTOR", "PHARMACIST", "CLINICAL_REVIEWER")),
):
    knowledge_version = _active_knowledge_version(db)
    knowledge_graph = MedicationKnowledgeGraph(data=knowledge_version.payload)
    # 1. Fetch Patient Profile from Database
    patient = db.query(models.Patient).filter(
        models.Patient.id == prescription.patient_id,
        models.Patient.organization_id == clinician.organization_id,
    ).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    # Format patient profile for the safety engine
    patient_profile = {
        "allergies": [{"allergy_name": a.allergy_name} for a in patient.allergies],
        "conditions": [{"condition_name": c.condition_name} for c in patient.conditions],
        "current_medications": [{"medication_name": m.medication_name} for m in patient.current_meds]
    }

    # This compatibility analysis route accepts only exact local-name parsing.
    # The result remains a draft; item-only requests must use the validated order API.
    if not prescription.raw_text or not prescription.raw_text.strip():
        raise HTTPException(
            status_code=409,
            detail="Submit validated structured orders to POST /api/v1/prescriptions; item-only legacy analysis is disabled.",
        )
    draft_parse = parse_prescription_draft(prescription.raw_text, knowledge_data=knowledge_version.payload)
    if not draft_parse["orders"]:
        raise HTTPException(
            status_code=422,
            detail="Medication could not be confidently normalized; use manual structured entry.",
        )

    parsed_items = []
    normalization_outcomes = []
    for proposed in draft_parse["orders"]:
        outcome = medication_terminology.normalize(
            proposed["medication_name"], knowledge_data=knowledge_version.payload
        ).as_dict()
        normalization_outcomes.append(outcome)
        if outcome["status"] != "NORMALIZED" or outcome["canonical_entity"] is None:
            raise HTTPException(status_code=422, detail=outcome["message"])
        parsed_items.append({
            "drug_name": outcome["canonical_entity"]["name"],
            "dose": proposed["dose"],
            "unit": proposed["unit"],
            "frequency": proposed["frequency"],
            "duration": proposed["duration"],
        })

    # 3. Save Prescription to Database (for history/audit)
    db_prescription = models.Prescription(
        patient_id=prescription.patient_id,
        organization_id=patient.organization_id,
        raw_text=prescription.raw_text,
        status=MedicationOrderStatus.DRAFT,
        parser_status=draft_parse["status"],
        source="LEGACY_ANALYSIS_DRAFT",
    )
    db.add(db_prescription)
    db.commit()
    db.refresh(db_prescription)

    for item in parsed_items:
        if "error" not in item:
            # Only pass fields that map to PrescriptionItem columns
            item_fields = {"drug_name", "dose", "unit", "frequency", "duration"}
            db_item = models.PrescriptionItem(prescription_id=db_prescription.id, **{k: v for k, v in item.items() if k in item_fields})
            db.add(db_item)
    db.add(AuditEvent(
        organization_id=patient.organization_id,
        action="PRESCRIPTION_CREATED",
        entity_type="Prescription",
        entity_id=str(db_prescription.id),
        details={"patient_id": patient.id, "parser_status": draft_parse["status"], "order_count": len(parsed_items), "source": "LEGACY_ANALYSIS_DRAFT"},
    ))
    for index, outcome in enumerate(normalization_outcomes):
        db.add(AuditEvent(
            organization_id=patient.organization_id,
            action="MEDICATION_NORMALIZATION_OUTCOME",
            entity_type="Prescription",
            entity_id=str(db_prescription.id),
            details={
                "order_index": index,
                "status": outcome["status"],
                "confidence": outcome["confidence"],
                "match_method": outcome["match_method"],
                "provider": outcome["provider"],
            },
        ))
    normalized_analysis = Analysis(
        organization_id=patient.organization_id,
        patient_id=patient.id,
        prescription_id=db_prescription.id,
        knowledge_version_id=knowledge_version.id,
        rule_set_version=f"{knowledge_version.dataset}:{knowledge_version.version}",
        status=AnalysisStatus.PARTIALLY_EVALUATED,
        allergy_checked=True,
        drug_drug_checked=True,
        drug_disease_checked=True,
        dose_checked=True,
        duplicate_therapy_checked=True,
    )
    db.add(normalized_analysis)
    db.flush()
    db.add(AuditEvent(
        organization_id=patient.organization_id,
        action="ANALYSIS_KNOWLEDGE_VERSION_RECORDED",
        entity_type="Analysis",
        entity_id=str(normalized_analysis.id),
        details={"knowledge_version_id": knowledge_version.id, "knowledge_version": knowledge_version.version,
                 "rule_set_version": normalized_analysis.rule_set_version, "checksum": knowledge_version.checksum},
    ))
    db.commit()

    # 4. Run Deterministic Safety Engine
    raw_alerts = safety_engine.analyze(patient_profile, parsed_items, knowledge_graph=knowledge_graph)
    severity_order = {"CRITICAL": 0, "HIGH": 1, "MODERATE": 2, "LOW": 3, "INFORMATIONAL": 4}
    raw_alerts.sort(key=lambda alert: severity_order.get(alert.get("severity", "INFORMATIONAL"), 4))

    # 5. Calculate Prototype Risk Score
    risk_result = calculate_risk_score(raw_alerts, knowledge_version.payload.get("priority_scoring"))

    # 6. Generate Explainable Clinical Warnings
    explained_alerts = explainability_engine.generate_explanations(raw_alerts, patient_profile, parsed_items, knowledge_version.payload)

    # 7. Return the complete, structured response to the frontend
    return {
        "id": db_prescription.id,
        "normalized_analysis_id": normalized_analysis.id,
        "knowledge_version": knowledge_version.version,
        "analysis_status": normalized_analysis.status.value,
        "safety_domains": {
            "allergy": normalized_analysis.allergy_checked,
            "drug_drug": normalized_analysis.drug_drug_checked,
            "drug_disease": normalized_analysis.drug_disease_checked,
            "dose": normalized_analysis.dose_checked,
            "duplicate_therapy": normalized_analysis.duplicate_therapy_checked,
            "renal": normalized_analysis.renal_checked,
            "hepatic": normalized_analysis.hepatic_checked,
            "pregnancy": normalized_analysis.pregnancy_checked,
            "age": normalized_analysis.age_checked,
        },
        "prescription_status": db_prescription.status.value,
        "parser_status": db_prescription.parser_status,
        "score": risk_result["score"],
        "risk_level": risk_result["risk_level"],
        "total_alerts": risk_result["total_alerts"],
        "disclaimer": risk_result["disclaimer"],
        "alerts": explained_alerts,
        "score_breakdown": risk_result["score_breakdown"]
    }


# Self-Improvement: Alert Feedback + Analysis History

@router.post("/prescriptions/analyze/{analysis_id}/feedback")

def record_feedback(

    analysis_id: int,

    feedback: schemas.FeedbackCreate,

    db: Session = Depends(get_db),

    clinician=Depends(require_clinician_roles("ADMIN", "DOCTOR", "PHARMACIST", "CLINICAL_REVIEWER")),

):

    # Verify the analysis exists

    analysis = db.query(models.Prescription).filter(
        models.Prescription.id == analysis_id,
        models.Prescription.organization_id == clinician.organization_id,
    ).first()

    if not analysis:

        raise HTTPException(status_code=404, detail="Analysis not found")



    # Pull alert_type and drug_name from the analysis history if available

    # (frontend may also send them directly in the feedback body)

    alert_type = feedback.alert_type if feedback.alert_type else None
    drug_name = feedback.drug_name if feedback.drug_name else None



    db_feedback = models.AlertFeedback(

        analysis_id=analysis_id,

        alert_index=feedback.alert_index,

        alert_type=alert_type,

        drug_name=drug_name,

        override_decision=feedback.override_decision,

        clinician_note=feedback.clinician_note,

    )

    db.add(db_feedback)
    db.flush()
    db.add(AuditEvent(
        organization_id=analysis.organization_id,
        actor_id=clinician.id,
        action="LEGACY_ANALYSIS_FEEDBACK_RECORDED",
        entity_type="Prescription",
        entity_id=str(analysis.id),
        details={"feedback_id": db_feedback.id, "alert_index": feedback.alert_index},
    ))
    db.commit()

    db.refresh(db_feedback)

    return {"message": "Feedback recorded", "data": db_feedback}


@router.get("/prescriptions/analyze/{analysis_id}")
def get_analysis_history(
    analysis_id: int,
    db: Session = Depends(get_db),
    clinician=Depends(require_clinician_roles("ADMIN", "DOCTOR", "PHARMACIST", "CLINICAL_REVIEWER", "READ_ONLY")),
):
    analysis = db.query(models.Prescription).filter(
        models.Prescription.id == analysis_id,
        models.Prescription.organization_id == clinician.organization_id,
    ).first()

    if not analysis:

        raise HTTPException(status_code=404, detail="Analysis not found")

    items = db.query(models.PrescriptionItem).filter(models.PrescriptionItem.prescription_id == analysis_id).all()

    feedback = db.query(models.AlertFeedback).filter(models.AlertFeedback.analysis_id == analysis_id).all()

    return {

        "id": analysis.id,

        "patient_id": analysis.patient_id,

        "raw_text": analysis.raw_text,

        "created_at": analysis.created_at,

        "items": [{"drug_name": i.drug_name, "dose": i.dose, "unit": i.unit, "frequency": i.frequency, "duration": i.duration} for i in items],

        "feedback": [{"id": f.id, "alert_index": f.alert_index, "alert_type": f.alert_type, "drug_name": f.drug_name, "override_decision": f.override_decision, "clinician_note": f.clinician_note, "created_at": f.created_at.isoformat() if f.created_at else None} for f in feedback],

    }


# --- Self-Improvement: Feedback Analytics ---

@router.get("/feedback/analytics")
def get_feedback_analytics(
    db: Session = Depends(get_db),
    clinician=Depends(require_clinician_roles("ADMIN", "DOCTOR", "PHARMACIST", "CLINICAL_REVIEWER", "READ_ONLY")),
):
    """Return organization-scoped descriptive metrics; feedback never changes rules or scores."""
    from collections import defaultdict
    from app.services.feedback_analyzer import analyze_feedback

    legacy_feedback = (
        db.query(models.AlertFeedback)
        .join(models.Prescription, models.Prescription.id == models.AlertFeedback.analysis_id)
        .join(models.Patient, models.Patient.id == models.Prescription.patient_id)
        .filter(models.Patient.organization_id == clinician.organization_id)
        .all()
    )
    enriched = [{
        "id": row.id,
        "analysis_id": row.analysis_id,
        "alert_index": row.alert_index,
        "alert_type": row.alert_type or "Unknown",
        "override_decision": row.override_decision,
        "clinician_note": None,
    } for row in legacy_feedback]
    analytics = analyze_feedback(enriched)

    normalized_feedback = db.query(Feedback).filter(
        Feedback.organization_id == clinician.organization_id,
    ).all()
    by_alert_type = defaultdict(lambda: defaultdict(int))
    by_rule_version = defaultdict(lambda: defaultdict(int))
    for row in normalized_feedback:
        decision = row.feedback.value if row.feedback else "UNKNOWN"
        by_alert_type[row.alert_type or "UNKNOWN"][decision] += 1
        by_rule_version[row.rule_version or "UNKNOWN"][decision] += 1

    analytics["rule_quality_monitoring"] = {
        "total_feedback": len(normalized_feedback),
        "by_alert_type": {key: dict(value) for key, value in by_alert_type.items()},
        "by_rule_version": {key: dict(value) for key, value in by_rule_version.items()},
        "changes_rules": False,
    }
    return analytics


# --- Self-Improvement: Re-analyze with feedback adaptations ---

@router.post("/prescriptions/analyze/{analysis_id}/reevaluate", response_model=schemas.AdaptedAnalysisResponse)
def reevaluate_with_feedback(
    analysis_id: int,
    db: Session = Depends(get_db),
    clinician=Depends(require_clinician_roles("ADMIN", "DOCTOR", "PHARMACIST", "CLINICAL_REVIEWER")),
):

    """Re-run the same deterministic rules; feedback is descriptive and cannot adjust results."""

    # Fetch the original analysis + patient + items
    analysis = db.query(models.Prescription).filter(
        models.Prescription.id == analysis_id,
        models.Prescription.organization_id == clinician.organization_id,
    ).first()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")

    recorded_analysis = db.query(Analysis).filter(Analysis.prescription_id == analysis_id).order_by(Analysis.id.desc()).first()
    if recorded_analysis is None or recorded_analysis.knowledge_version_id is None:
        raise HTTPException(status_code=409, detail="Analysis has no recorded knowledge version and cannot be safely reevaluated.")
    knowledge_version = db.query(KnowledgeVersion).filter(KnowledgeVersion.id == recorded_analysis.knowledge_version_id).first()
    if knowledge_version is None or not isinstance(knowledge_version.payload, dict):
        raise HTTPException(status_code=503, detail="Recorded knowledge version is unavailable.")

    patient = db.query(models.Patient).filter(
        models.Patient.id == analysis.patient_id,
        models.Patient.organization_id == clinician.organization_id,
    ).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    items = db.query(models.PrescriptionItem).filter(models.PrescriptionItem.prescription_id == analysis_id).all()

    # Reconstruct patient profile
    patient_profile = {
        "allergies": [{"allergy_name": a.allergy_name} for a in patient.allergies],
        "conditions": [{"condition_name": c.condition_name} for c in patient.conditions],
        "current_medications": [{"medication_name": m.medication_name} for m in patient.current_meds],
    }

    # Reconstruct parsed items
    parsed_items = [{"drug_name": i.drug_name, "dose": i.dose, "unit": i.unit, "frequency": i.frequency, "duration": i.duration} for i in items]

    raw_alerts = safety_engine.analyze(patient_profile, parsed_items, knowledge_graph=MedicationKnowledgeGraph(data=knowledge_version.payload))
    severity_order = {"CRITICAL": 0, "HIGH": 1, "MODERATE": 2, "LOW": 3, "INFORMATIONAL": 4}
    raw_alerts.sort(key=lambda a: severity_order.get(a.get("severity", "INFORMATIONAL"), 4))
    risk_result = calculate_risk_score(raw_alerts, knowledge_version.payload.get("priority_scoring"))
    explained_alerts = explainability_engine.generate_explanations(raw_alerts, patient_profile, parsed_items, knowledge_version.payload)

    return {
        "id": analysis.id,
        "knowledge_version": knowledge_version.version,
        "score": risk_result["score"],
        "risk_level": risk_result["risk_level"],
        "total_alerts": risk_result["total_alerts"],
        "disclaimer": risk_result["disclaimer"],
        "alerts": explained_alerts,
        "score_breakdown": risk_result["score_breakdown"],
        "feedback_adapted": False,
        "adapted_types": [],
    }


# FHIR Integration Endpoint
@router.post("/fhir/analyze")
def analyze_fhir_bundle(
    fhir_bundle: dict,
    db: Session = Depends(get_db),
    clinician=Depends(require_clinician_roles("ADMIN", "DOCTOR", "PHARMACIST", "CLINICAL_REVIEWER")),
):
    """Validates and normalizes an externally supplied R4 Bundle before analysis."""
    try:
        validate_bundle(fhir_bundle)
    except FHIRValidationError as exc:
        raise HTTPException(status_code=422, detail={"message": str(exc), "issues": exc.issues}) from exc
    knowledge_version = _active_knowledge_version(db)
    knowledge_graph = MedicationKnowledgeGraph(data=knowledge_version.payload)
    try:
        canonical = normalize_bundle(
            fhir_bundle,
            lambda name: _normalization_outcome(name, knowledge_version.payload),
            max_age_hours=settings.FHIR_CONTEXT_MAX_AGE_HOURS,
        )
    except FHIRValidationError as exc:
        raise HTTPException(status_code=422, detail={"message": str(exc), "issues": exc.issues}) from exc
    patient_profile = {
        "allergies": [{"allergy_name": item["substance"]} for item in canonical["allergies"] if item["substance"]],
        "conditions": [{"condition_name": item["code"]} for item in canonical["conditions"] if item["code"]],
        "current_medications": [
            {"medication_name": item["medication"]["normalized_name"]}
            for item in canonical["medication_statements"]
            if item["medication"].get("normalization_status") == "NORMALIZED"
        ],
    }
    new_prescriptions = [
        {"drug_name": item["medication"]["normalized_name"], "dose": item["dose"], "unit": item["unit"], "frequency": item["frequency"]}
        for item in canonical["medication_requests"]
        if item["medication"].get("normalization_status") == "NORMALIZED"
        and item["status"] in {"active", "on-hold"}
    ]

    raw_alerts = safety_engine.analyze(patient_profile, new_prescriptions, knowledge_graph=knowledge_graph)
    risk_result = calculate_risk_score(raw_alerts, knowledge_version.payload.get("priority_scoring"))
    explained_alerts = explainability_engine.generate_explanations(
        raw_alerts, patient_profile, new_prescriptions, knowledge_version.payload
    )

    return {
        "message": "FHIR Bundle processed successfully",
        "analysis_status": "COMPLETE" if canonical["data_quality"]["fhir_context"]["freshness"] == "CURRENT" and canonical["data_quality"]["medication_normalization"] == "NORMALIZED" else "INCOMPLETE",
        "data_quality": canonical["data_quality"],
        "fhir_context": canonical,
        "knowledge_version": knowledge_version.version,
        "score": risk_result["score"],
        "risk_level": risk_result["risk_level"],
        "alerts": explained_alerts,
    }


@router.get("/fhir/smart/authorize")
async def fhir_smart_authorize(clinician=Depends(require_clinician_roles("ADMIN", "DOCTOR", "CLINICAL_REVIEWER"))):
    try:
        return {"authorization_url": await smart_fhir_client.authorization_url(str(clinician.id))}
    except Exception as exc:
        # Never include upstream response bodies or credentials in errors/logs.
        raise HTTPException(status_code=503, detail="FHIR authorization is unavailable; check SMART configuration.") from exc


@router.get("/fhir/smart/callback")
async def fhir_smart_callback(state: str, code: str):
    owner = smart_fhir_client.authorization_owner(state)
    if owner is None:
        raise HTTPException(status_code=400, detail="SMART authorization state is invalid or expired.")
    try:
        return await smart_fhir_client.exchange_code(owner, state, code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="FHIR authorization failed; re-authentication is required.") from exc


@router.get("/fhir/smart/patient-context")
async def fhir_smart_patient_context(clinician=Depends(require_clinician_roles("ADMIN", "DOCTOR", "CLINICAL_REVIEWER"))):
    try:
        _, context = await smart_fhir_client.access_token(str(clinician.id))
        bundle = await smart_fhir_client.fetch_patient_bundle(str(clinician.id))
        db = next(get_db())
        try:
            knowledge_version = _active_knowledge_version(db)
            canonical = normalize_bundle(bundle, lambda name: _normalization_outcome(name, knowledge_version.payload), max_age_hours=settings.FHIR_CONTEXT_MAX_AGE_HOURS)
        finally:
            db.close()
        return {"context": canonical, "token_expires_at": context.expires_at, "reauthentication_required": False}
    except FHIRValidationError as exc:
        raise HTTPException(status_code=422, detail={"message": str(exc), "issues": exc.issues}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="FHIR context is unavailable; re-authentication or server recovery is required.") from exc


@router.get("/system/status")
def get_system_status():
    """Returns the result of direct checks for configured service dependencies."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        db_status = "Connected"
    except Exception:
        logger.warning("Database status check failed")
        db_status = "Disconnected"

    try:
        nlp("system status check")
        nlp_status = "available"
    except Exception:
        logger.warning("NLP status check failed")
        nlp_status = "unavailable"

    return {
        "app_name": settings.APP_NAME,
        "version": settings.VERSION,
        "database": db_status,
        "services": {"nlp_engine": nlp_status},
    }
