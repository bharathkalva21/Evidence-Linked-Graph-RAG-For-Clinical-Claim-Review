"""Step 7 report contract: review sections resolve to the original claims."""

from backend.agents.report import ReportGenerator
from backend.schemas.patient import LinkedEntity, MedicationStatement, PatientContext
from backend.schemas.report import ClinicalClaim, ClinicalReport, DiagnosisCandidate
from ingestion.authoritative_sources import build_passages, load_manifest


def test_representative_report_preserves_claim_links_safety_and_unknowns():
    sources = [item for entries in build_passages(load_manifest()).values() for item, _ in entries]
    nice = next(item for item in sources if item.section == "Recommendation 1.4.35")
    label = next(item for item in sources if item.section.startswith("4 CONTRAINDICATIONS"))
    context = PatientContext(
        raw_input="60-year-old with confirmed hypertension, takes amlodipine, allergy status not supplied",
        age=60, hypertension_scope=True, hypertension_confirmed=True,
        medication_list_status="reported",
        medication_statements=[MedicationStatement(name="amlodipine", status="current",
                                                   source_phrase="takes amlodipine")],
        allergy_status="unknown", missing_information=["Allergy status not supplied"],
        known_conditions=[LinkedEntity(text="hypertension", entity_type="disease")],
    )
    diagnosis = ClinicalClaim(claim_id="diagnosis-1", claim_type="diagnosis",
                              text="Hypertension remains in the differential", status="unverified",
                              applies_to="Hypertension", unverified_reason="Needs clinician review")
    investigation = ClinicalClaim(claim_id="investigation-1", claim_type="investigation",
                                  text="Confirm blood pressure measurement", status="unverified",
                                  applies_to="Hypertension", supporting_evidence_ids=[nice.id],
                                  unverified_reason="Passage does not verify this investigation")
    treatment = ClinicalClaim(claim_id="treatment-1", claim_type="treatment",
                              text="A calcium channel blocker may be considered", status="unverified",
                              applies_to="Hypertension", conditions=["Confirmed hypertension"],
                              missing_checks=["Allergy status not supplied"],
                              supporting_evidence_ids=[nice.id], unverified_reason="Eligibility needs review")
    warning = ClinicalClaim(claim_id="warning-1", claim_type="medication_warning",
                            text="Amlodipine sensitivity is a contraindication", status="supported",
                            supporting_evidence_ids=[label.id])
    report = ReportGenerator().generate(
        context=context, diagnoses=[DiagnosisCandidate(diagnosis="Hypertension", confidence=0.8)],
        evidence=[], conflicts=[{"type": "allergy_status_unconfirmed", "severity": "medium",
                                 "verification_status": "unverified",
                                 "description": "Allergy status needs confirmation"}],
        missing_info=context.missing_information, confidence=0.8,
        limitations=["Clinician review required"],
        claims=[diagnosis, investigation, treatment, warning], source_passages=[nice, label],
        evidence_completeness={"claim_count": 4, "unverified_claims": 3, "supported_claims": 1},
        verification_failures=["Treatment eligibility unverified"],
    )
    wire = report.model_dump(mode="json")
    assert wire["ranked_diagnoses"][0]["diagnosis"] == "Hypertension"  # legacy field
    assert wire["overall_confidence"] == 0.8  # retained as an uncalibrated legacy score
    assert wire["confidence_calibrated"] is False
    assert wire["differential"][0]["diagnostic_claim_ids"] == ["diagnosis-1"]
    assert wire["unassigned_diagnostic_claim_ids"] == []
    assert wire["differential"][0]["treatment_claim_ids"] == ["treatment-1"]
    assert wire["investigation_claim_ids"] == ["investigation-1"]
    assert wire["treatment_claim_ids"] == ["treatment-1"]
    assert wire["medication_safety"]["current_medications"] == ["amlodipine"]
    assert wire["medication_safety"]["allergy_status"] == "unknown"
    assert wire["medication_safety"]["warning_claim_ids"] == ["warning-1"]
    assert wire["medication_safety"]["findings"][0]["verification_status"] == "unverified"
    assert wire["source_passages"][0]["url"].endswith("#ng136-1_4_35")
    assert "Treatment eligibility unverified" in wire["verification_failures"]
    assert ClinicalReport.model_validate(wire).model_dump(mode="json") == wire


def test_report_rejects_grouped_reference_to_wrong_claim_type():
    from pydantic import ValidationError

    context = PatientContext(raw_input="case")
    claim = ClinicalClaim(claim_id="one", claim_type="diagnosis", text="Candidate",
                          status="unverified", unverified_reason="No source")
    report = ReportGenerator().generate(context, [], [], [], [], 0.0, [], claims=[claim])
    data = report.model_dump()
    data["treatment_claim_ids"] = ["one"]
    try:
        ClinicalReport.model_validate(data)
    except ValidationError:
        pass
    else:
        raise AssertionError("Wrong claim type should not satisfy a treatment reference")


def test_unmatched_diagnostic_claim_remains_available_to_ui():
    context = PatientContext(raw_input="case")
    claim = ClinicalClaim(claim_id="asthma-candidate", claim_type="diagnosis", text="Asthma is possible",
                          status="unverified", applies_to="Asthma", unverified_reason="No source")
    report = ReportGenerator().generate(
        context, [DiagnosisCandidate(diagnosis="Model synthesis unavailable", confidence=0)],
        [], [], [], 0, [], claims=[claim])
    assert report.differential[0].diagnostic_claim_ids == []
    assert report.unassigned_diagnostic_claim_ids == ["asthma-candidate"]
