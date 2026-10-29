"""Independent, fail-closed check of proposed claims against pinned source text."""

from dataclasses import dataclass, field

from backend.schemas.evidence import SourcePassage
from backend.schemas.patient import PatientContext
from backend.schemas.report import ClinicalClaim


@dataclass
class VerificationResult:
    claims: list[ClinicalClaim]
    trusted_passages: list[SourcePassage] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    evidence_completeness: dict[str, int] = field(default_factory=dict)


class ClaimVerifier:
    def __init__(self, pinned_passages: list[SourcePassage] | None = None):
        self._pinned_passages = pinned_passages

    def _load_pinned(self) -> tuple[dict[str, SourcePassage], str | None]:
        if self._pinned_passages is not None:
            return {item.id: item for item in self._pinned_passages}, None
        try:
            from ingestion.authoritative_sources import build_passages, load_manifest

            grouped = build_passages(load_manifest())  # checks local SHA-256 and SPL version
            return {item.id: item for entries in grouped.values() for item, _ in entries}, None
        except (OSError, ValueError) as exc:
            return {}, f"Pinned source snapshot unavailable or changed: {exc}"

    def verify(
        self, context: PatientContext, claims: list[ClinicalClaim],
        retrieved_passages: list[SourcePassage],
    ) -> VerificationResult:
        pinned, load_error = self._load_pinned()
        retrieved = {item.id: item for item in retrieved_passages}
        trusted = {key: item for key, item in retrieved.items()
                   if key in pinned and item == pinned[key]
                   and item.source_type in {"guideline", "drug_label"}}
        failures = [load_error] if load_error else []
        checked = []
        for claim in claims:
            reasons = []
            cited = (claim.supporting_evidence_ids + claim.conflicting_evidence_ids
                     + claim.unverified_evidence_ids)
            invalid = [key for key in cited if key not in trusted]
            if invalid:
                reasons.append("Citation does not match an available pinned document version and passage: "
                               + ", ".join(invalid))
            if not cited:
                reasons.append("No cited source passage")
            if claim.rejected_evidence_ids:
                reasons.append("Rejected citation IDs require review")
            if claim.claim_type == "treatment":
                if claim.missing_checks:
                    reasons.append("Patient-specific prerequisites remain unchecked")
                if context.allergy_status in {"unknown", "conflicting"}:
                    reasons.append("Allergy status is unknown or conflicting")
                if context.medication_list_status in {"unknown", "conflicting"}:
                    reasons.append("Current medication list is unknown or conflicting")
                if context.hypertension_scope and context.hypertension_confirmed is not True:
                    reasons.append("Hypertension is not documented as confirmed")
            for key in cited:
                source = trusted.get(key)
                if not source:
                    continue
                if source.source_type == "guideline" and source.document_id == "NG136":
                    if claim.applies_to and "hypertension" not in claim.applies_to.casefold():
                        reasons.append("NICE hypertension passage has a different clinical population or condition")
                    if context.age is not None and context.age < 18:
                        reasons.append("NICE adult guideline does not apply to a child")
                    if context.pregnancy_status == "pregnant" and claim.claim_type == "treatment":
                        reasons.append("NICE hypertension treatment section excludes pregnancy")
                    if claim.claim_type == "treatment" and source.section == "Recommendation 1.4.35":
                        if context.age is None:
                            reasons.append("Age for step 1 treatment is unknown")
                        if any("type 2 diabetes" in condition.casefold() for condition in
                               [entity.text for entity in context.known_conditions]):
                            reasons.append("Recommendation 1.4.35 excludes type 2 diabetes")
                    if claim.claim_type == "diagnosis" and source.section.startswith("Recommendation 1.4."):
                        reasons.append("Treatment recommendation cannot establish a diagnosis")
                    if claim.claim_type == "investigation" and source.section.startswith("Recommendation 1.4."):
                        reasons.append("Treatment recommendation does not support the proposed investigation")
                    if "amlodipine allergy" in claim.text.casefold():
                        reasons.append("NICE treatment passage does not establish amlodipine contraindication")
                if source.source_type == "drug_label" and claim.claim_type == "diagnosis":
                    reasons.append("A drug label does not establish this patient's diagnosis")
                if source.source_type == "drug_label" and source.document_id.startswith("SPL-"):
                    if claim.applies_to and not any(term in claim.applies_to.casefold() for term in
                                                    ("amlodipine", "hypertension")):
                        reasons.append("Amlodipine label does not cover the stated condition")
                    if "simvastatin" in claim.text.casefold() and "simvastatin" not in source.passage.casefold():
                        reasons.append("Cited label passage does not discuss simvastatin")
                    if "allerg" in claim.text.casefold() and "sensitivity" not in source.passage.casefold():
                        reasons.append("Cited label passage does not discuss amlodipine sensitivity")
            # No generic textual entailment or patient applicability is inferred from a citation.
            reasons.append("Claim meaning, population, intervention, outcome, and jurisdiction need clinician review")
            reason = "; ".join(dict.fromkeys(reasons))
            failures.extend(f"{claim.claim_id}: {item}" for item in dict.fromkeys(reasons)
                            if item != "Claim meaning, population, intervention, outcome, and jurisdiction need clinician review")
            checked.append(claim.model_copy(update={"status": "unverified", "unverified_reason": reason}))
        counts = {
            "claim_count": len(checked),
            "pinned_passages_available": len(trusted),
            "validated_citations": len({key for claim in claims for key in
                                        (claim.supporting_evidence_ids + claim.conflicting_evidence_ids
                                         + claim.unverified_evidence_ids) if key in trusted}),
            "invalid_citations": len({key for claim in claims for key in
                                      (claim.supporting_evidence_ids + claim.conflicting_evidence_ids
                                       + claim.unverified_evidence_ids) if key not in trusted}),
            "supported_claims": 0,
            "unverified_claims": len(checked),
        }
        return VerificationResult(checked, list(trusted.values()), list(dict.fromkeys(failures)), counts)
