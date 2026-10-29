from typing import List, Dict, Any
from backend.schemas.patient import PatientContext
from backend.schemas.evidence import EvidenceItem, SourcePassage
from backend.schemas.report import (
    ClinicalClaim, ClinicalReport, DiagnosisCandidate, DifferentialEntry,
    MedicationSafetySummary,
)

class ReportGenerator:
    def generate(
        self, 
        context: PatientContext, 
        diagnoses: List[DiagnosisCandidate], 
        evidence: List[EvidenceItem], 
        conflicts: List[Dict[str, Any]], 
        missing_info: List[str],
        confidence: float,
        limitations: List[str],
        claims: List[ClinicalClaim] | None = None,
        source_passages: List[SourcePassage] | None = None,
        evidence_completeness: Dict[str, int] | None = None,
        verification_failures: List[str] | None = None,
    ) -> ClinicalReport:
        """
        Constructs the final Clinical Report.
        """
        disclaimer = (
            "WARNING: This is a research/educational decision-support output and MUST NOT be used "
            "as a medical diagnosis. A licensed clinician must review all findings."
        )
        
        # Summarize only facts that were actually extracted.
        person = f"{context.age}-year-old patient" if context.age is not None else "Patient (age not supplied)"
        if context.sex:
            person += f", sex recorded as {context.sex}"
        summary_parts = [person + "."]
        if context.symptoms:
            summary_parts.append("Reported symptoms: " + ", ".join(item.text for item in context.symptoms) + ".")
        if context.known_conditions:
            summary_parts.append("Known conditions: " + ", ".join(item.text for item in context.known_conditions) + ".")
        if context.hypertension_scope:
            state = ("documented as confirmed" if context.hypertension_confirmed is True
                     else "documented as excluded" if context.hypertension_confirmed is False
                     else "not confirmed from the supplied text")
            summary_parts.append("Hypertension: " + state + ".")
        summary = " ".join(summary_parts)
        
        # Add safety note to diagnoses based on conflicts
        for d in diagnoses:
            for c in conflicts:
                if d.diagnosis in c.get("description", ""):
                    d.safety_notes.append(f"SAFETY WARNING: {c.get('description')}")
        
        # Default limitations
        report_limitations = limitations.copy()
        report_limitations.append("The system relies on local automated extraction and may miss nuances in the clinical text.")
        
        all_claims = claims or []
        differential = []
        for rank, diagnosis in enumerate(diagnoses, start=1):
            related = [claim for claim in all_claims if (claim.applies_to or "").casefold()
                       == diagnosis.diagnosis.casefold()]
            differential.append(DifferentialEntry(
                rank=rank, diagnosis=diagnosis.diagnosis,
                diagnostic_claim_ids=[claim.claim_id for claim in related if claim.claim_type == "diagnosis"],
                investigation_claim_ids=[claim.claim_id for claim in related if claim.claim_type == "investigation"],
                treatment_claim_ids=[claim.claim_id for claim in related if claim.claim_type == "treatment"],
            ))
        safety_types = {
            "graph_contraindication_candidate", "graph_interaction_candidate",
            "amlodipine_label_missing", "allergy_status_unconfirmed",
            "amlodipine_allergy", "medication_list_unconfirmed", "amlodipine_simvastatin",
        }
        safety = MedicationSafetySummary(
            current_medications=list(dict.fromkeys(
                item.name for item in context.medication_statements if item.status == "current"
                and item.extraction_certainty == "explicit"
            )),
            medication_list_status=context.medication_list_status,
            allergies=[item.text for item in context.allergies],
            allergy_status=context.allergy_status,
            findings=[item for item in conflicts if item.get("type") in safety_types],
            warning_claim_ids=[claim.claim_id for claim in all_claims if claim.claim_type == "medication_warning"],
        )
        assigned_diagnostic_ids = {claim_id for entry in differential for claim_id in entry.diagnostic_claim_ids}

        return ClinicalReport(
            disclaimer=disclaimer,
            case_summary=summary,
            ranked_diagnoses=diagnoses,
            missing_information=missing_info,
            conflicts=conflicts,
            overall_confidence=confidence,
            limitations=report_limitations,
            references=evidence,
            claims=all_claims,
            source_passages=source_passages or [],
            evidence_completeness=evidence_completeness or {},
            verification_failures=verification_failures or [],
            differential=differential,
            unassigned_diagnostic_claim_ids=[claim.claim_id for claim in all_claims
                                             if claim.claim_type == "diagnosis"
                                             and claim.claim_id not in assigned_diagnostic_ids],
            investigation_claim_ids=[claim.claim_id for claim in all_claims if claim.claim_type == "investigation"],
            treatment_claim_ids=[claim.claim_id for claim in all_claims if claim.claim_type == "treatment"],
            medication_safety=safety,
        )
