"""Generate candidate clinical claims from retrieved evidence and patient context."""

from dataclasses import dataclass
from typing import Any

from backend.schemas.evidence import EvidenceItem
from backend.schemas.patient import PatientContext
from backend.schemas.report import ClinicalClaim, DiagnosisCandidate
from backend.schemas.retrieval import OrchestratorResult
from backend.services.claim_synthesis import ClaimProposal, normalize_claims
from backend.services.llm_fallback import LLMFallback


@dataclass
class FusionResult:
    diagnoses: list[DiagnosisCandidate]
    missing_information: list[str]
    investigations: list[str]
    claims: list[ClinicalClaim]


class ClinicalFusion:
    def __init__(self):
        self.llm = LLMFallback()

    @staticmethod
    def _proposals(data: dict[str, Any]) -> list[ClaimProposal]:
        proposals = []
        for key, claim_type in (
            ("diagnostic_claims", "diagnosis"),
            ("investigations_to_consider", "investigation"),
            ("treatment_options_if_confirmed", "treatment"),
        ):
            for item in data[key]:
                if not isinstance(item, dict):
                    raise ValueError(f"{key} must contain objects")
                proposals.append(ClaimProposal.model_validate({**item, "claim_type": claim_type}))
        return proposals

    @classmethod
    def _validate_response(cls, data: dict[str, Any]) -> None:
        if "medicines_to_use" in data:
            raise ValueError("Imperative medicine output is not accepted")
        for key in ("diagnoses", "diagnostic_claims", "investigations_to_consider",
                    "treatment_options_if_confirmed", "missing_information"):
            if not isinstance(data.get(key), list):
                raise ValueError(f"{key} must be a list")
        if any(not isinstance(item, str) or not item.strip() for item in data["missing_information"]):
            raise ValueError("missing_information must contain nonblank strings")
        for item in data["diagnoses"]:
            if not isinstance(item, dict) or not isinstance(item.get("diagnosis"), str):
                raise ValueError("Each diagnosis needs a name and a score")
            diagnosis = DiagnosisCandidate.model_validate(item)
            if not diagnosis.diagnosis.strip() or not 0 <= diagnosis.confidence <= 1:
                raise ValueError("Diagnosis name and score are invalid")
        cls._proposals(data)

    def fuse(
        self,
        context: PatientContext,
        retrieval_result: OrchestratorResult,
        ranked_evidence: list[EvidenceItem],
        conflicts: list[dict[str, Any]],
    ) -> FusionResult:
        prompt = self._build_prompt(context, retrieval_result, ranked_evidence, conflicts)
        parsed = self.llm.generate_json(
            prompt,
            "You are a clinical evidence extraction assistant. Return only valid JSON; never declare a claim verified.",
            validate=self._validate_response,
        )
        if parsed is None:
            graph_names = [item.get("name") for item in retrieval_result.graph_results.candidate_diseases]
            graph_names = [name.strip() for name in graph_names if isinstance(name, str) and name.strip()]
            fallback = DiagnosisCandidate(
                diagnosis="LLM synthesis unavailable; graph candidates: " + ", ".join(graph_names[:5])
                if graph_names else "LLM synthesis unavailable",
                confidence=0.0,
                safety_notes=["Model synthesis failed; graph links are unverified candidate signals."],
            )
            proposals = [ClaimProposal(claim_type="diagnosis", text=f"{name} is a differential candidate",
                                       applies_to=name) for name in graph_names[:5]]
            return FusionResult([fallback], ["Model synthesis unavailable"], [],
                                normalize_claims(proposals, retrieval_result.source_passages[:12], context))

        # Keep the legacy diagnosis fields for existing API clients, but do not put
        # free-text medicines or tests there without a claim and source identity.
        diagnoses = [DiagnosisCandidate(diagnosis=item["diagnosis"].strip(), confidence=item["confidence"])
                     for item in parsed["diagnoses"]]
        proposals = self._proposals(parsed)
        for diagnosis in diagnoses:
            if not any(p.claim_type == "diagnosis" and
                       (p.applies_to or "").casefold() == diagnosis.diagnosis.casefold() for p in proposals):
                proposals.append(ClaimProposal(claim_type="diagnosis",
                                               text=f"{diagnosis.diagnosis} is a differential candidate",
                                               applies_to=diagnosis.diagnosis))
        claims = normalize_claims(proposals, retrieval_result.source_passages[:12], context)
        investigations = [claim.text for claim in claims if claim.claim_type == "investigation"]
        return FusionResult(diagnoses, parsed["missing_information"], investigations, claims)

    @staticmethod
    def _build_prompt(context, retrieval_result, ranked_evidence, conflicts) -> str:
        source_lines = []
        for source in retrieval_result.source_passages[:12]:
            source_lines.append(
                f"[{source.id}] {source.source_type}; {source.publisher}; {source.title}; "
                f"version {source.document_version}; {source.section}; {source.url}\n"
                f"PASSAGE: {source.passage}"
            )
        candidate_lines = [f"- {item.title}: {item.text[:250]}" for item in ranked_evidence[:8]]
        if not source_lines:
            source_lines = ["No authoritative source passage was retrieved; leave source ID lists empty."]
        return (
            "Create a ranked differential and candidate claims for clinician review. "
            "Use graph, textbook, DrugCentral, and web results only to suggest candidates; "
            "only the authoritative source IDs listed below may be cited. "
            "Do not infer a diagnosis or medication safety from a guideline or drug label alone. "
            "Keep evidence for and against a claim in separate lists. "
            "Do not output medicines_to_use, prescriptions, or imperative treatment directions.\n\n"
            f"Patient statement: {context.raw_input}\n"
            f"Symptoms: {[item.text for item in context.symptoms]}\n"
            f"Known conditions: {[item.text for item in context.known_conditions]}\n"
            f"Current medicines: {[item.text for item in context.medications]}\n"
            f"Medication list status: {context.medication_list_status}\n"
            f"Allergy status: {context.allergy_status}; allergies: {[item.text for item in context.allergies]}\n"
            f"Blood pressure: {[item.model_dump() for item in context.blood_pressure_readings]}\n"
            f"Hypertension confirmed in statement: {context.hypertension_confirmed}\n"
            f"Pregnancy status: {context.pregnancy_status}\n"
            f"Labs: {context.labs}\n"
            f"Missing checks: {context.missing_information}\n"
            f"Detected conflicts: {conflicts}\n\n"
            "Candidate signals (not citable):\n" + "\n".join(candidate_lines) + "\n\n"
            "Authoritative passages and permitted citation IDs:\n" + "\n".join(source_lines) + "\n\n"
            "Return one JSON object with these keys, using empty arrays when appropriate:\n"
            '{"diagnoses":[{"diagnosis":"Condition name","confidence":0.5}],'
            '"diagnostic_claims":[{"text":"Diagnostic possibility","applies_to":"Condition name",'
            '"conditions":[],"supporting_evidence_ids":[],"conflicting_evidence_ids":[],"unverified_evidence_ids":[]}],'
            '"investigations_to_consider":[{"text":"Investigation to discuss",'
            '"applies_to":"Condition name","conditions":[],"missing_checks":[],'
            '"supporting_evidence_ids":[],"conflicting_evidence_ids":[],"unverified_evidence_ids":[]}],'
            '"treatment_options_if_confirmed":[{"text":"Conditional option to discuss",'
            '"applies_to":"Condition name","conditions":["Diagnosis confirmed"],'
            '"missing_checks":["Patient-specific checks"],"supporting_evidence_ids":[],'
            '"conflicting_evidence_ids":[],"unverified_evidence_ids":[]}],'
            '"missing_information":[]}\n'
            "Every treatment must name its applicable diagnosis or condition, prerequisites, and missing checks. "
            "Cite a passage only when it appears relevant; do not invent IDs."
        )
