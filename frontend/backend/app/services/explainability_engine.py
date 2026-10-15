from typing import List, Dict, Any

class ExplainabilityEngine:
    def generate_explanations(self, alerts: List[Dict[str, Any]], patient_profile: Dict[str, Any], prescription: List[Dict[str, Any]], knowledge_data: dict | None = None) -> List[Dict[str, Any]]:
        """
        Transforms raw safety alerts into highly structured, human-readable clinical explanations.
        """
        explained_alerts = []

        for alert in alerts:
            alert_type = alert.get("type", "Unknown")
            severity = alert.get("severity", "INFORMATIONAL")
            
            # Base explanation structure that answers the 6 required questions
            explanation = {
                "severity": severity,
                "type": alert_type,
                "what_detected": "",
                "involved_entities": [],
                "why_flagged": "",
                "trigger_info": "",
                "evidence": alert.get("evidence", "Knowledge-base evidence unavailable"),
                "source": alert.get("source", "System"),
                "recommended_action": ""
            }

            # 1. Drug-Drug Interaction
            if alert_type == "Drug-Drug Interaction":
                drug_a = alert.get("drug_a", "Drug A")
                drug_b = alert.get("drug_b", "Drug B")
                explanation["what_detected"] = "Potential Drug-Drug Interaction"
                explanation["involved_entities"] = [drug_a, drug_b]
                explanation["why_flagged"] = alert.get("reason", "These medications may interact.")
                explanation["trigger_info"] = f"New prescription contains '{drug_a}' while patient profile lists current medication '{drug_b}'."
                explanation["recommended_action"] = "Review this finding with a clinician."

            # 2. Drug-Disease Interaction
            elif alert_type == "Drug-Disease Interaction":
                drug = alert.get("drug", "Drug")
                condition = alert.get("condition", "Condition")
                explanation["what_detected"] = "Drug-Disease Contraindication"
                explanation["involved_entities"] = [drug, condition]
                explanation["why_flagged"] = alert.get("reason", "This medication may worsen the patient's condition.")
                explanation["trigger_info"] = f"Prescribed '{drug}' conflicts with patient's diagnosed condition: '{condition}'."
                explanation["recommended_action"] = "Review this finding with a clinician."

            # 3. Allergy Conflict
            elif alert_type == "Allergy Conflict":
                allergen = alert.get("allergen", "Allergen")
                drug = alert.get("drug", "Drug")
                explanation["what_detected"] = "CRITICAL: Patient Allergy Conflict"
                explanation["involved_entities"] = [allergen, drug]
                explanation["why_flagged"] = alert.get("reason", "Patient is allergic to this medication or its class.")
                explanation["trigger_info"] = f"Patient has a recorded allergy to '{allergen}'. The prescribed '{drug}' belongs to this class or cross-reacts."
                explanation["recommended_action"] = "Review this finding with a clinician."

            # 4. Duplicate Medication
            elif alert_type in ["Duplicate Medication", "Therapeutic Duplicate"]:
                drug = alert.get("drug", alert.get("drug_a", "Drug"))
                explanation["what_detected"] = "Duplicate Therapy Detected"
                explanation["involved_entities"] = [drug, alert.get("drug_b", "Current Medication")]
                explanation["why_flagged"] = alert.get("reason", "Patient is already receiving this therapy.")
                explanation["trigger_info"] = f"The prescription and current medication records both include '{drug}'."
                explanation["recommended_action"] = "Review this finding with a clinician."

            # 5. Dosage Error / Verification
            elif alert_type in ["Dosage Error", "Dosage Verification"]:
                drug = alert.get("drug", "Drug")
                dose = alert.get("prescribed_dose", "Unknown dose")
                explanation["what_detected"] = "Dosage Safety Check"
                explanation["involved_entities"] = [drug]
                explanation["why_flagged"] = alert.get("reason", "Dosage requires clinical verification.")
                explanation["trigger_info"] = f"Prescribed dose for '{drug}' is '{dose}'."
                
                if alert_type == "Dosage Error":
                    explanation["recommended_action"] = "Review this finding with a clinician."
                else:
                    explanation["recommended_action"] = "Review this finding with a clinician."

            template = (knowledge_data or {}).get("explanation_templates", {}).get(alert_type, {})
            explanation["what_detected"] = template.get("what_detected", explanation["what_detected"])
            explanation["recommended_action"] = template.get("recommended_action", explanation["recommended_action"])

            explained_alerts.append(explanation)

        return explained_alerts

# Instantiate the engine
explainability_engine = ExplainabilityEngine()
