from typing import List, Dict, Any

def calculate_risk_score(alerts: List[Dict[str, Any]], priority_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Calculates a deterministic Prototype Medication Safety Risk Score (0-100).
    Returns the score, risk level, and a transparent breakdown of how it was calculated.
    """
    severity_points = priority_config["severity_points"]
    risk_levels = priority_config["risk_levels"]
    max_score = priority_config["max_score"]
    total_score = 0
    breakdown = []

    # 1. Calculate points based on alerts
    for alert in alerts:
        severity = alert.get("severity", "INFORMATIONAL").upper()
        points = severity_points.get(severity, 0)
        
        total_score += points
        
        # Record how this specific alert contributed to the score
        breakdown.append({
            "alert_type": alert.get("type", "Unknown"),
            "severity": severity,
            "points_added": points,
            "details": f"{alert.get('drug', '')} {alert.get('drug_a', '')} {alert.get('drug_b', '')}".strip()
        })

    # 2. Cap the score at 100
    final_score = min(total_score, max_score)

    # 3. Determine the Risk Level based on thresholds
    risk_level = "Unknown"
    for level in risk_levels:
        if level["minimum"] <= final_score <= level["maximum"]:
            risk_level = level["label"]
            break

    # 4. Return the structured, explainable result
    return {
        "score": final_score,
        "max_score": max_score,
        "risk_level": risk_level,
        "total_alerts": len(alerts),
        "score_breakdown": breakdown,
        "disclaimer": "Rule-Based Alert Priority Score. Prototype output for clinician review; it is not a validated clinical tool."
    }
