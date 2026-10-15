import json
import os
from pathlib import Path

import networkx as nx


class MedicationKnowledgeGraph:
    def __init__(self, json_path: str | None = None, data: dict | None = None):
        self.graph = nx.DiGraph()
        self.json_path = str(json_path or Path(__file__).resolve().parents[3] / "knowledge_base" / "versions" / "v1.json")
        self.knowledge_data = data
        self._load_data()

    def _load_data(self):
        """Loads JSON data and builds the NetworkX graph."""
        # Determine path reliably both locally and inside Docker.
        if not os.path.exists(self.json_path):
            # Docker: knowledge_base/ is mounted/copied to /knowledge_base/
            alt = os.path.join(os.path.dirname(__file__), "..", "..", "..", "knowledge_base", os.path.basename(self.json_path))
            if os.path.exists(alt):
                self.json_path = alt
            else:
                alt = os.path.join("/knowledge_base", os.path.basename(self.json_path))
                if os.path.exists(alt):
                    self.json_path = alt

        data = self.knowledge_data
        if data is None:
            with open(self.json_path, "r", encoding="utf-8") as knowledge_file:
                data = json.load(knowledge_file)
        if isinstance(data, dict) and isinstance(data.get("manifest"), dict) and isinstance(data.get("data"), dict):
            data = data["data"]
        self.knowledge_data = data

        # 1. Add Drug Nodes
        for drug, info in data.get("drugs", {}).items():
            self.graph.add_node(drug, type="drug", **info)

        # 2. Add Drug-Drug Interaction Edges
        for interaction in data.get("drug_drug_interactions", []):
            edge_data = {
                "relation": "INTERACTS_WITH",
                "severity": interaction["severity"],
                "reason": interaction["reason"],
                "evidence": interaction["evidence"],
            }
            self.graph.add_edge(interaction["drug_a"], interaction["drug_b"], **edge_data)
            # Add reverse edge for bidirectional checking.
            self.graph.add_edge(interaction["drug_b"], interaction["drug_a"], **edge_data)

        # 3. Add Drug-Disease Contraindication Edges
        for contraindication in data.get("drug_disease_contraindications", []):
            self.graph.add_edge(
                contraindication["drug"],
                contraindication["disease"],
                relation="CONTRAINDICATED_IN",
                severity=contraindication["severity"],
                reason=contraindication["reason"],
                evidence=contraindication["evidence"],
            )

        # 4. Add Allergy Cross-Reactivity Edges
        for allergy in data.get("allergy_cross_reactivity", []):
            self.graph.add_edge(
                allergy["allergen"],
                allergy["trigger_drug"],
                relation="TRIGGERS_ALLERGY",
                severity=allergy["severity"],
                reason=allergy["reason"],
                evidence=allergy["evidence"],
            )

    def get_drug_info(self, drug_name: str):
        """Returns drug details if it exists in the graph."""
        if self.graph.has_node(drug_name):
            return self.graph.nodes[drug_name]
        return None

    def check_interaction(self, drug_a: str, drug_b: str):
        """Checks only the pinned, imported file/database snapshot."""
        if self.graph.has_edge(drug_a, drug_b):
            edge_data = self.graph[drug_a][drug_b]
            if edge_data.get("relation") == "INTERACTS_WITH":
                return edge_data
        return None

    def get_duplicate_rule(self, therapeutic_class: str):
        for rule in self.knowledge_data.get("duplicate_therapeutic_classes", []):
            if rule.get("class", "").casefold() == therapeutic_class.casefold():
                return rule
        return None

    def get_exact_duplicate_rule(self):
        return self.knowledge_data.get("duplicate_medication_rule")

    def get_dosage_rule(self, over_limit: bool):
        key = "dosage_limit_rule" if over_limit else "dosage_verification_rule"
        return self.knowledge_data.get(key)

    def check_disease_contraindication(self, drug: str, disease: str):
        """Checks if a drug is contraindicated for a specific disease."""
        if self.graph.has_edge(drug, disease):
            edge_data = self.graph[drug][disease]
            if edge_data.get("relation") == "CONTRAINDICATED_IN":
                return edge_data
        return None

    def check_allergy_trigger(self, allergen: str, drug: str):
        """Checks if a drug triggers a known allergy."""
        if self.graph.has_edge(allergen, drug):
            edge_data = self.graph[allergen][drug]
            if edge_data.get("relation") == "TRIGGERS_ALLERGY":
                return edge_data
        return None


# Instantiate a global instance for the app to use.
med_kg = MedicationKnowledgeGraph()
