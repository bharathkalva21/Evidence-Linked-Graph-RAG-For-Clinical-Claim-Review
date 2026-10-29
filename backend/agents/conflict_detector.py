import hashlib
import re
from typing import List, Dict, Any
from backend.schemas.patient import PatientContext
from backend.schemas.retrieval import OrchestratorResult
from backend.schemas.evidence import EvidenceItem, SourcePassage
from backend.schemas.report import ClinicalClaim

class ConflictDetector:
    def detect(
        self, 
        context: PatientContext, 
        retrieval_result: OrchestratorResult, 
        ranked_evidence: List[EvidenceItem]
    ) -> List[Dict[str, Any]]:
        """
        Detects contradictions (contraindications, drug-drug interactions, missing symptoms).
        Returns a list of conflict dictionaries with severity.
        """
        conflicts = []
        
        # 1. Check Drug Contraindications from Graph Results
        for contra in retrieval_result.graph_results.contraindications:
            drug = contra.get("drug")
            disease = contra.get("disease")
            # If the disease is one of the top candidates, we flag it
            candidate_names = [d.get("name") for d in retrieval_result.graph_results.candidate_diseases]
            if disease in candidate_names:
                conflicts.append({
                    "type": "graph_contraindication_candidate",
                    "severity": "medium",
                    "verification_status": "unverified",
                    "description": f"Graph suggests a potential concern involving '{drug}' and '{disease}'; check an authoritative label before treating it as a contraindication."
                })
        
        # 2. Check Drug-Drug Interactions
        for interaction in retrieval_result.graph_results.drug_interactions:
            conflicts.append({
                "type": "graph_interaction_candidate",
                "severity": "medium",
                "verification_status": "unverified",
                "description": f"Graph suggests a possible interaction between {interaction.get('drug_a')} and {interaction.get('drug_b')}; verify against an authoritative label."
            })
            
        # 3. Weak Evidence Check
        if retrieval_result.graph_results.candidate_diseases and not ranked_evidence:
            conflicts.append({
                "type": "weak_evidence",
                "severity": "medium",
                "description": "Candidates generated but no strong evidence found to support them."
            })
            
        # 4. Critical Missing Information
        if not context.age or not context.sex:
            conflicts.append({
                "type": "missing_info",
                "severity": "low",
                "description": "Demographic information (age/sex) is incomplete."
            })
            
        return conflicts

    def detect_medication_safety(
        self, context: PatientContext, trusted_passages: List[SourcePassage],
        claims: List[ClinicalClaim],
    ) -> tuple[List[Dict[str, Any]], List[ClinicalClaim]]:
        """Apply only exact, pinned amlodipine label rules; unknown facts cause abstention."""
        conflicts: List[Dict[str, Any]] = []
        warnings: List[ClinicalClaim] = []
        current = {item.name.casefold() for item in context.medication_statements
                   if item.status == "current" and item.extraction_certainty == "explicit"}
        proposed = any(claim.claim_type == "treatment" and
                       re.search(r"\bamlodipine\b", claim.text, re.I) for claim in claims)
        relevant = proposed or "amlodipine" in current
        if not relevant:
            return conflicts, warnings

        def label(section: str, required: tuple[str, ...]) -> SourcePassage | None:
            for source in trusted_passages:
                if (source.source_type == "drug_label"
                        and source.document_id == "SPL-0c5784b9-5542-144f-e063-6394a90a7ebc"
                        and section in source.section
                        and all(term in source.passage.casefold() for term in required)):
                    return source
            return None

        def warn(kind: str, description: str, source: SourcePassage | None, severity: str):
            conflicts.append({"type": kind, "severity": severity,
                              "verification_status": "supported" if source else "unverified",
                              "source_passage_id": source.id if source else None,
                              "description": description})
            if source:
                warnings.append(ClinicalClaim(
                    claim_id="claim_" + hashlib.sha256((kind + description + source.id).encode()).hexdigest()[:20],
                    claim_type="medication_warning", text=description, status="supported",
                    applies_to="Amlodipine exposure", supporting_evidence_ids=[source.id],
                ))

        if not any(source.source_type == "drug_label" and
                   source.document_id == "SPL-0c5784b9-5542-144f-e063-6394a90a7ebc"
                   for source in trusted_passages):
            warn("amlodipine_label_missing", "Pinned amlodipine label was not retrieved; medication safety is unverified.",
                 None, "medium")

        if context.allergy_status in {"unknown", "conflicting"}:
            warn("allergy_status_unconfirmed", "Amlodipine safety cannot be cleared until allergy status is confirmed.",
                 None, "medium")
        elif context.allergy_status == "allergies_reported" and any(
            item.text.casefold() == "amlodipine" and item.extraction_certainty == "explicit"
            for item in context.allergies
        ):
            source = label("4 CONTRAINDICATIONS", ("contraindicated", "sensitivity", "amlodipine"))
            warn("amlodipine_allergy", "Reported amlodipine allergy conflicts with amlodipine use; review and avoid until reconciled.",
                 source, "high")
            for index, claim in enumerate(claims):
                if claim.claim_type == "treatment" and re.search(r"\bamlodipine\b", claim.text, re.I):
                    if source:
                        existing = [key for key in claim.conflicting_evidence_ids if key != source.id]
                        claims[index] = claim.model_copy(update={
                            "status": "conflicting", "conflicting_evidence_ids": existing + [source.id],
                            "supporting_evidence_ids": [key for key in claim.supporting_evidence_ids if key != source.id],
                            "unverified_evidence_ids": [key for key in claim.unverified_evidence_ids if key != source.id],
                            "unverified_reason": None,
                        })
                    else:
                        claims[index] = claim.model_copy(update={
                            "status": "unverified",
                            "unverified_reason": "Reported amlodipine allergy; pinned contraindication passage unavailable",
                        })

        if context.medication_list_status in {"unknown", "conflicting"}:
            warn("medication_list_unconfirmed", "Amlodipine interactions cannot be cleared until current medicines are confirmed.",
                 None, "medium")
        elif "simvastatin" in current:
            source = label("7.2 Impact of Amlodipine on Other Drugs", ("simvastatin", "amlodipine", "20 mg daily"))
            warn("amlodipine_simvastatin", "Amlodipine with current simvastatin requires dose and interaction review against the label.",
                 source, "high" if source else "medium")
        return conflicts, warnings
