from typing import List, Dict, Any
from app.services.knowledge_graph import med_kg

class MedicationSafetyEngine:
    def __init__(self):
        self.kg = med_kg

    def analyze(self, patient_profile: Dict[str, Any], new_prescription: List[Dict[str, Any]], knowledge_graph=None) -> List[Dict[str, Any]]:
        """
        Main orchestrator that runs all 5 safety checks.
        """
        alerts = []
        kg = knowledge_graph or self.kg
        
        # Extract patient data
        allergies = patient_profile.get("allergies", [])
        conditions = patient_profile.get("conditions", [])
        current_meds = patient_profile.get("current_medications", [])
        
        # Extract new drug names from the parsed prescription
        new_drugs = [item["drug_name"] for item in new_prescription if "drug_name" in item]

        # Run the 5 checks
        alerts.extend(self._check_drug_drug_interactions(new_drugs, current_meds, kg))
        alerts.extend(self._check_drug_disease_interactions(new_drugs, conditions, kg))
        alerts.extend(self._check_duplicate_medications(new_drugs, current_meds, kg))
        alerts.extend(self._check_allergy_conflicts(new_drugs, allergies, kg))
        alerts.extend(self._check_dosages(new_prescription, kg))

        return alerts

    def _check_drug_drug_interactions(self, new_drugs: List[str], current_meds: List[str], kg) -> List[Dict]:
        alerts = []
        # Extract just the names from current meds if they are dicts
        current_med_names = [med["medication_name"] if isinstance(med, dict) else med for med in current_meds]

        for new_drug in new_drugs:
            for current_med in current_med_names:
                interaction = kg.check_interaction(new_drug, current_med)
                if interaction:
                    alerts.append({
                        "type": "Drug-Drug Interaction",
                        "severity": interaction["severity"],
                        "drug_a": new_drug,
                        "drug_b": current_med,
                        "reason": interaction["reason"],
                        "evidence": interaction["evidence"],
                        "source": interaction.get("source", "Drug Knowledge Graph")
                    })
        return alerts

    def _check_drug_disease_interactions(self, new_drugs: List[str], conditions: List[str], kg) -> List[Dict]:
        alerts = []
        # Extract just the names from conditions if they are dicts
        condition_names = [cond["condition_name"] if isinstance(cond, dict) else cond for cond in conditions]

        for new_drug in new_drugs:
            for condition in condition_names:
                contraindication = kg.check_disease_contraindication(new_drug, condition)
                if contraindication:
                    alerts.append({
                        "type": "Drug-Disease Interaction",
                        "severity": contraindication["severity"],
                        "drug": new_drug,
                        "condition": condition,
                        "reason": contraindication["reason"],
                        "evidence": contraindication["evidence"],
                        "source": "Drug Knowledge Graph"
                    })
        return alerts

    def _check_duplicate_medications(self, new_drugs: List[str], current_meds: List[str], kg) -> List[Dict]:
        alerts = []
        current_med_names = [med["medication_name"] if isinstance(med, dict) else med for med in current_meds]
        exact_rule = kg.get_exact_duplicate_rule()

        # 1. Exact duplicate check
        for new_drug in new_drugs:
            if new_drug in current_med_names and exact_rule:
                alerts.append({
                    "type": "Duplicate Medication",
                    "severity": exact_rule["severity"],
                    "drug": new_drug,
                    "reason": exact_rule["reason"],
                    "evidence": exact_rule.get("evidence", "Knowledge-base evidence unavailable"),
                    "source": "Database Record"
                })
        
        # 2. Therapeutic class duplicate check (e.g., two NSAIDs)
        for i, drug_a in enumerate(new_drugs):
            for drug_b in new_drugs[i+1:]:
                info_a = kg.get_drug_info(drug_a)
                info_b = kg.get_drug_info(drug_b)
                duplicate_rule = kg.get_duplicate_rule(info_a.get("class")) if info_a and info_a.get("class") else None
                if info_a and info_b and duplicate_rule and info_a.get("class") == info_b.get("class"):
                    alerts.append({
                        "type": "Therapeutic Duplicate",
                        "severity": duplicate_rule["severity"],
                        "drug_a": drug_a,
                        "drug_b": drug_b,
                        "reason": duplicate_rule["reason"],
                        "evidence": duplicate_rule.get("evidence", "Knowledge-base evidence unavailable"),
                        "source": "Drug Knowledge Graph"
                    })
        return alerts

    def _check_allergy_conflicts(self, new_drugs: List[str], allergies: List[str], kg) -> List[Dict]:
        alerts = []
        # Extract just the names from allergies if they are dicts
        allergy_names = [allergy["allergy_name"] if isinstance(allergy, dict) else allergy for allergy in allergies]

        for new_drug in new_drugs:
            for allergy in allergy_names:
                trigger = kg.check_allergy_trigger(allergy, new_drug)
                if trigger:
                    alerts.append({
                        "type": "Allergy Conflict",
                        "severity": trigger["severity"],
                        "allergen": allergy,
                        "drug": new_drug,
                        "reason": trigger["reason"],
                        "evidence": trigger["evidence"],
                        "source": "Allergy Cross-Reactivity Database"
                    })
        return alerts

    def _check_dosages(self, new_prescription: List[Dict[str, Any]], kg) -> List[Dict]:
        alerts = []
        
        for item in new_prescription:
            drug_name = item.get("drug_name")
            dose = item.get("dose")
            unit = item.get("unit")
            
            if not drug_name or not dose:
                continue

            # Try to get max dose from Knowledge Graph
            drug_info = kg.get_drug_info(drug_name)
            
            limit_rule = kg.get_dosage_rule(over_limit=True)
            if (
                drug_info and "max_daily_dose_mg" in drug_info and limit_rule
                and unit and unit.upper() == "MG"
            ):
                max_dose = drug_info["max_daily_dose_mg"]
                
                # Basic check: if unit is mg and dose exceeds max
                if float(dose) > max_dose:
                    alerts.append({
                        "type": "Dosage Error",
                        "severity": limit_rule["severity"],
                        "drug": drug_name,
                        "prescribed_dose": f"{dose} {unit}",
                        "max_safe_dose": f"{max_dose} mg",
                        "reason": limit_rule["reason_template"].format(
                            dose=dose, unit=unit, max_dose=max_dose, drug=drug_name,
                        ),
                        "evidence": limit_rule["evidence_reference"],
                        "source": "Drug Knowledge Graph"
                    })
            else:
                rule = kg.get_dosage_rule(over_limit=False)
                alerts.append({
                    "type": "Dosage Verification",
                    "severity": rule["severity"] if rule else "UNKNOWN",
                    "drug": drug_name,
                    "prescribed_dose": f"{dose} {unit}" if unit else dose,
                    "reason": rule["reason"] if rule else "Insufficient data to evaluate",
                    "evidence": rule["evidence_reference"] if rule else "Reference data unavailable",
                    "source": "System Limitation"
                })
                
        return alerts

# Instantiate the engine
safety_engine = MedicationSafetyEngine()
