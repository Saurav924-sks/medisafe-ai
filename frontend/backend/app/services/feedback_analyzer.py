from typing import Dict, List, Any
from collections import defaultdict

def analyze_feedback(feedback_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Summarizes explicit clinician votes for descriptive quality monitoring only.

    feedback_list entries: {
        "id": int,
        "analysis_id": int,
        "alert_index": int,
        "override_decision": bool | None,   # True=Agree(correct), False=Disagree(incorrect)
        "clinician_note": str | None,
    }

    Returns:
        {
            "total_feedback": int,
            "agreement_rate": float,          # fraction marked Agree
            "disagreement_rate": float,       # fraction marked Disagree
            "per_type_stats": {               # keyed by alert_type
                "alert_type": {
                    "total": int,
                    "agreed": int,
                    "disagreed": int,
                    "disagreement_rate": float,
                    "adjustment_factor": float,   # 1.0 = no change, <1.0 = reduce weight
                    "adapted": bool,              # True if we have enough samples to adapt
                }
            },
            "adapted_types": List[str],       # compatibility field; always empty
            "system_version": str,
        }
    """
    if not feedback_list:
        return {
            "total_feedback": 0,
            "agreement_rate": 0.0,
            "disagreement_rate": 0.0,
            "per_type_stats": {},
            "adapted_types": [],
            "system_version": "1.0.0",
        }

    # Group feedback by alert type — we need the alert_type from the original analysis.
    # Since feedback only stores alert_index, we join on analysis_id + alert_index.
    # For this prototype we receive pre-grouped data from the route.
    # The route will pass us a list of dicts that include alert_type.

    type_stats = defaultdict(lambda: {"total": 0, "agreed": 0, "disagreed": 0})

    for fb in feedback_list:
        decision = fb.get("override_decision")
        alert_type = fb.get("alert_type", "Unknown")
        if not isinstance(decision, bool):
            continue
        if decision:
            type_stats[alert_type]["agreed"] += 1
        else:
            type_stats[alert_type]["disagreed"] += 1
        type_stats[alert_type]["total"] += 1

    per_type = {}
    adapted_types = []
    total_agreed = 0
    total_disagreed = 0
    total_all = 0

    for alert_type, stats in type_stats.items():
        total = stats["total"]
        agreed = stats["agreed"]
        disagreed = stats["disagreed"]
        disagreement_rate = disagreed / total if total > 0 else 0.0

        total_agreed += agreed
        total_disagreed += disagreed
        total_all += total

        per_type[alert_type] = {
            "total": total,
            "agreed": agreed,
            "disagreed": disagreed,
            "disagreement_rate": round(disagreement_rate, 3),
            "adjustment_factor": 1.0,
            "adapted": False,
        }

    return {
        "total_feedback": total_all,
        "agreement_rate": round(total_agreed / total_all, 3) if total_all > 0 else 0.0,
        "disagreement_rate": round(total_disagreed / total_all, 3) if total_all > 0 else 0.0,
        "per_type_stats": per_type,
        "adapted_types": [],
        "system_version": "1.0.0",
    }
