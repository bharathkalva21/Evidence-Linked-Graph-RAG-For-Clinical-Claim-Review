"""Step 6: pinned identity, applicability, and narrow label-backed safety gates."""

import pytest

from backend.agents.conflict_detector import ConflictDetector
from backend.agents.fusion import FusionResult
from backend.agents.report import ReportGenerator
from backend.api import routes
from backend.schemas.evidence import SourcePassage
from backend.schemas.patient import LinkedEntity, MedicationStatement, PatientContext
from backend.schemas.report import ClinicalClaim
from backend.schemas.report import DiagnosisCandidate
from backend.schemas.retrieval import GraphRetrievalResult, OrchestratorResult, VectorRetrievalResult
from backend.services.claim_verifier import ClaimVerifier
from ingestion.authoritative_sources import build_passages, load_manifest


@pytest.fixture(scope="module")
def pinned():
    return [source for entries in build_passages(load_manifest()).values() for source, _ in entries]


def find(pinned, section):
    return next(source for source in pinned if section in source.section)


def claim(source_id, text="Amlodipine may be considered if hypertension is confirmed",
          claim_type="treatment", applies_to="Hypertension"):
    return ClinicalClaim(claim_id="claim_candidate", claim_type=claim_type, text=text,
                         status="unverified", applies_to=applies_to,
                         conditions=["Confirmed hypertension"],
                         supporting_evidence_ids=[source_id],
                         unverified_reason="Pending verification")


def context(**changes):
    data = dict(raw_input="case", age=60, hypertension_scope=True,
                hypertension_confirmed=True, allergy_status="no_known_allergies",
                medication_list_status="none_reported")
    data.update(changes)
    return PatientContext(**data)


def test_wrong_citation_does_not_support_claim(pinned):
    source = find(pinned, "Recommendation 1.4.35")
    proposal = claim(source.id, "Amlodipine allergy is a contraindication")
    result = ClaimVerifier(pinned).verify(context(), [proposal], [source])
    assert result.claims[0].status == "unverified"
    assert any("does not establish amlodipine contraindication" in item for item in result.failures)


def test_wrong_population_and_child_are_rejected(pinned):
    source = find(pinned, "Recommendation 1.4.35")
    result = ClaimVerifier(pinned).verify(
        PatientContext(raw_input="child", age=12), [claim(source.id, applies_to="Asthma")], [source])
    assert result.claims[0].status == "unverified"
    assert any("adult guideline does not apply" in item for item in result.failures)
    assert any("different clinical population" in item for item in result.failures)


def test_old_version_and_forged_passage_fail_closed(pinned):
    source = find(pinned, "Recommendation 1.4.35")
    old = SourcePassage(**{**source.model_dump(exclude={"id"}), "document_version": "2019-08-28"})
    forged = SourcePassage(**{**source.model_dump(exclude={"id"}), "passage": "Offer all drugs to all patients.",
                              "span_end": len("Offer all drugs to all patients.")})
    for supplied in (old, forged):
        result = ClaimVerifier(pinned).verify(context(), [claim(supplied.id)], [supplied])
        assert result.evidence_completeness["invalid_citations"] == 1
        assert any("pinned document version and passage" in item for item in result.failures)


def test_allergy_conflicts_with_proposed_amlodipine_and_cites_label(pinned):
    source = find(pinned, "4 CONTRAINDICATIONS")
    allergy = LinkedEntity(text="amlodipine", entity_type="drug", extraction_certainty="explicit",
                           source_phrase="allergic to amlodipine")
    patient = context(allergy_status="allergies_reported", allergies=[allergy])
    proposed = [claim(source.id)]
    verified = ClaimVerifier(pinned).verify(patient, proposed, [source])
    conflicts, warnings = ConflictDetector().detect_medication_safety(patient, verified.trusted_passages,
                                                                       verified.claims)
    assert verified.claims[0].status == "conflicting"
    assert source.id in verified.claims[0].conflicting_evidence_ids
    assert any(item["type"] == "amlodipine_allergy" and item["verification_status"] == "supported"
               for item in conflicts)
    assert warnings[0].status == "supported" and warnings[0].supporting_evidence_ids == [source.id]


def test_unknown_allergy_and_missing_source_abstain(pinned):
    patient = PatientContext(raw_input="case", allergy_status="unknown", medication_list_status="unknown")
    proposed = [claim("missing-label")]
    verified = ClaimVerifier(pinned).verify(patient, proposed, [])
    conflicts, warnings = ConflictDetector().detect_medication_safety(patient, verified.trusted_passages,
                                                                       verified.claims)
    assert verified.claims[0].status == "unverified"
    assert warnings == []
    assert {item["type"] for item in conflicts} >= {
        "amlodipine_label_missing", "allergy_status_unconfirmed", "medication_list_unconfirmed"}
    assert all(item["verification_status"] == "unverified" for item in conflicts)


def test_simvastatin_warning_requires_exact_label_passage(pinned):
    label = find(pinned, "7.2 Impact of Amlodipine on Other Drugs")
    patient = PatientContext(raw_input="takes simvastatin", allergy_status="no_known_allergies",
                             medication_list_status="reported",
                             medication_statements=[MedicationStatement(
                                 name="simvastatin", status="current", source_phrase="takes simvastatin")])
    proposed = [claim(label.id)]
    checked = ClaimVerifier(pinned).verify(patient, proposed, [label])
    conflicts, warnings = ConflictDetector().detect_medication_safety(patient, checked.trusted_passages,
                                                                       checked.claims)
    assert any(item["type"] == "amlodipine_simvastatin" and item["source_passage_id"] == label.id
               for item in conflicts)
    assert any(item.status == "supported" and item.supporting_evidence_ids == [label.id]
               for item in warnings)


def test_graph_contraindication_is_only_an_unverified_lead():
    graph = GraphRetrievalResult(candidate_diseases=[{"name": "Hypertension"}], paths=[],
                                 contraindications=[{"drug": "amlodipine", "disease": "Hypertension"}])
    result = OrchestratorResult(graph_results=graph, vector_results=VectorRetrievalResult())
    findings = ConflictDetector().detect(context(), result, [])
    assert findings[0]["verification_status"] == "unverified"
    assert findings[0]["type"] == "graph_contraindication_candidate"


def test_positive_label_warning_and_recommendation_review(pinned):
    """Manual-review sample: exact contraindication and CCB sections remain scoped."""
    label = find(pinned, "4 CONTRAINDICATIONS")
    nice = find(pinned, "Recommendation 1.4.35")
    assert "known sensitivity to amlodipine" in label.passage.casefold()
    assert "aged 55 or over" in nice.passage.casefold()
    assert "do not have type 2 diabetes" in nice.passage.casefold()
    checked = ClaimVerifier(pinned).verify(context(), [claim(nice.id)], [nice])
    assert checked.claims[0].status == "unverified"  # jurisdiction and full applicability unreviewed


def test_analyze_route_reports_verified_warning_and_separate_completeness(monkeypatch, pinned):
    label = find(pinned, "4 CONTRAINDICATIONS")
    allergy = LinkedEntity(text="amlodipine", entity_type="drug", extraction_certainty="explicit",
                           source_phrase="allergic to amlodipine")
    patient = context(allergy_status="allergies_reported", allergies=[allergy])

    class Clarifier:
        def process(self, raw):
            return patient

    class Orchestrator:
        def retrieve(self, _):
            return OrchestratorResult(graph_results=GraphRetrievalResult(candidate_diseases=[], paths=[]),
                                      vector_results=VectorRetrievalResult(), source_passages=[label])

    class Ranker:
        def rank(self, *args):
            return []

    class Fusion:
        def fuse(self, *args):
            return FusionResult([DiagnosisCandidate(diagnosis="Hypertension", confidence=0.8)], [], [],
                                [claim(label.id)])

    class Confidence:
        def evaluate(self, *args):
            return 0.8, "report"

    class Retry:
        max_retries = 0

        def should_retry(self, *args):
            return False

    monkeypatch.setattr(routes, "get_pipeline", lambda: {
        "clarifier": Clarifier(), "orchestrator": Orchestrator(), "ranker": Ranker(),
        "detector": ConflictDetector(), "fusion": Fusion(), "verifier": ClaimVerifier(pinned),
        "confidence": Confidence(), "retry": Retry(), "report": ReportGenerator(),
    })
    report = routes.analyze_case(routes.AnalyzeRequest(case_text="case"))["report"]
    assert {item["status"] for item in report["claims"]} == {"conflicting", "supported"}
    assert report["evidence_completeness"]["supported_claims"] == 1
    assert report["evidence_completeness"]["conflicting_claims"] == 1
    assert report["confidence_calibrated"] is False
    assert any(item["type"] == "amlodipine_allergy" for item in report["conflicts"])
    assert report["differential"][0]["diagnosis"] == "Hypertension"
    assert report["treatment_claim_ids"] == ["claim_candidate"]
    assert report["medication_safety"]["allergy_status"] == "allergies_reported"
    assert report["medication_safety"]["warning_claim_ids"]
    assert report["medication_safety"]["findings"][0]["source_passage_id"] == label.id
