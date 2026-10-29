"""Step 5 claim proposals remain conditional and structurally traceable."""

import json
from datetime import date

import pytest

from backend.agents.fusion import ClinicalFusion
from backend.agents.report import ReportGenerator
from backend.api import routes
from backend.schemas.evidence import SourcePassage
from backend.schemas.patient import PatientContext
from backend.schemas.retrieval import GraphRetrievalResult, OrchestratorResult, VectorRetrievalResult
from backend.services.llm_fallback import LLMFallback


def passage(section="Recommendation 1.4.35", source_type="guideline"):
    text = "Consider a conditional option for adults with confirmed hypertension and eligibility."
    return SourcePassage(
        source_type=source_type, source_name="Pinned source", publisher="Example authority",
        document_id=f"doc-{source_type}", document_version="2026-01", title="Clinical guidance",
        document_date=date(2026, 1, 1), url="https://example.org/guidance",
        jurisdiction="Example", section=section, span_start=0, span_end=len(text),
        passage=text,
    )


def retrieval(*sources, graph_names=()):
    return OrchestratorResult(
        graph_results=GraphRetrievalResult(
            candidate_diseases=[{"name": name, "score": 0.5} for name in graph_names], paths=[]),
        vector_results=VectorRetrievalResult(), source_passages=list(sources),
    )


def response(**overrides):
    data = {
        "diagnoses": [{"diagnosis": "Hypertension", "confidence": 0.6,
                       "treatment_considerations": ["Start an uncited drug"]}],
        "diagnostic_claims": [],
        "investigations_to_consider": [],
        "treatment_options_if_confirmed": [],
        "missing_information": [],
    }
    data.update(overrides)
    return data


def fusion_with_response(data):
    fusion = ClinicalFusion()
    fusion.llm.generate_json = lambda *args, **kwargs: data
    return fusion


def test_valid_source_linked_claims_keep_evidence_roles_and_conditions():
    support = passage()
    conflict = passage(section="Recommendation 1.4.34")
    context = PatientContext(raw_input="Adult with hypertension", hypertension_scope=True,
                             missing_information=["Allergy status not supplied"])
    data = response(
        diagnostic_claims=[{"text": "Hypertension remains in the differential", "applies_to": "Hypertension",
                            "supporting_evidence_ids": [support.id], "conflicting_evidence_ids": [conflict.id]}],
        investigations_to_consider=[{"text": "Discuss blood pressure confirmation",
                                     "applies_to": "Hypertension", "conditions": ["Diagnosis not yet confirmed"],
                                     "supporting_evidence_ids": [support.id]}],
        treatment_options_if_confirmed=[{"text": "A calcium channel blocker may be considered",
                                         "applies_to": "Hypertension", "conditions": ["Patient eligible"],
                                         "missing_checks": ["Review comorbidities"],
                                         "supporting_evidence_ids": [support.id],
                                         "conflicting_evidence_ids": [conflict.id]}],
    )
    result = fusion_with_response(data).fuse(context, retrieval(support, conflict), [], [])
    assert {claim.claim_type for claim in result.claims} == {"diagnosis", "investigation", "treatment"}
    assert all(claim.status == "unverified" for claim in result.claims)
    treatment = next(claim for claim in result.claims if claim.claim_type == "treatment")
    assert treatment.applies_to == "Hypertension"
    assert treatment.supporting_evidence_ids == [support.id]
    assert treatment.conflicting_evidence_ids == [conflict.id]
    assert "Allergy status not supplied" in treatment.missing_checks
    assert "Diagnosis or condition confirmed: Hypertension" in treatment.conditions
    assert result.diagnoses[0].treatment_considerations == []
    assert result.diagnoses[0].recommended_tests == []

    report = ReportGenerator().generate(context, result.diagnoses, [], [], [], 0.5, [],
                                        claims=result.claims, source_passages=[support, conflict])
    assert len(report.claims) == 3
    assert len(report.source_passages) == 2
    assert report.ranked_diagnoses[0].treatment_considerations == []
    assert report.model_dump(mode="json")["claims"][0]["status"] == "unverified"


def test_citation_free_and_unknown_ids_remain_unverified():
    context = PatientContext(raw_input="Hypertension is possible")
    data = response(treatment_options_if_confirmed=[{
        "text": "A medicine class might be considered", "applies_to": "Hypertension",
        "conditions": ["Diagnosis confirmed"], "supporting_evidence_ids": ["web-snippet-123"],
    }])
    result = fusion_with_response(data).fuse(context, retrieval(), [], [])
    treatment = next(claim for claim in result.claims if claim.claim_type == "treatment")
    assert treatment.status == "unverified"
    assert treatment.supporting_evidence_ids == []
    assert treatment.rejected_evidence_ids == ["web-snippet-123"]
    assert "No available authoritative passage" in treatment.unverified_reason
    assert any(claim.claim_type == "diagnosis" and claim.status == "unverified" for claim in result.claims)
    report = ReportGenerator().generate(context, result.diagnoses, [], [], [], 0.5, [], claims=result.claims)
    assert report.claims


def test_imperative_medicine_field_is_rejected():
    with pytest.raises(ValueError, match="Imperative medicine"):
        ClinicalFusion._validate_response(response(medicines_to_use=["amlodipine"]))
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        ClinicalFusion._validate_response(response(treatment_options_if_confirmed=[{
            "text": "A medicine may be considered", "applies_to": "Hypertension",
            "conditions": ["Diagnosis confirmed"], "medicines_to_use": ["amlodipine"],
        }]))


def test_conflicting_roles_are_moved_to_unverified_evidence():
    source = passage()
    data = response(diagnostic_claims=[{
        "text": "Hypertension remains possible", "applies_to": "Hypertension",
        "supporting_evidence_ids": [source.id], "conflicting_evidence_ids": [source.id],
    }])
    result = fusion_with_response(data).fuse(PatientContext(raw_input="Hypertension"), retrieval(source), [], [])
    claim = result.claims[0]
    assert claim.supporting_evidence_ids == []
    assert claim.conflicting_evidence_ids == []
    assert claim.unverified_evidence_ids == [source.id]
    assert "conflicting evidence roles" in claim.unverified_reason


def test_invalid_first_provider_falls_back_to_valid_structured_output():
    attempts = []
    invalid = response(treatment_options_if_confirmed=[{
        "text": "Start amlodipine", "applies_to": "Hypertension", "conditions": ["Confirmed"],
    }])
    valid = response()

    def provider(name, result):
        def call(*args):
            attempts.append(name)
            return result if isinstance(result, str) else json.dumps(result)
        return (name, "test-key", call)

    fusion = ClinicalFusion()
    llm = LLMFallback()
    llm.providers = (provider("malformed", "{not JSON"), provider("invalid", invalid),
                     provider("valid", valid))
    fusion.llm = llm
    result = fusion.fuse(PatientContext(raw_input="Hypertension"), retrieval(), [], [])
    assert attempts == ["malformed", "invalid", "valid"]
    assert result.diagnoses[0].diagnosis == "Hypertension"
    assert result.claims[0].status == "unverified"


def test_all_provider_failure_keeps_graph_candidates_unverified():
    fusion = ClinicalFusion()
    fusion.llm.generate_json = lambda *args, **kwargs: None
    result = fusion.fuse(PatientContext(raw_input="Case"), retrieval(graph_names=["Asthma"]), [], [])
    assert "Asthma" in result.diagnoses[0].diagnosis
    assert result.claims[0].applies_to == "Asthma"
    assert result.claims[0].status == "unverified"
    assert result.claims[0].supporting_evidence_ids == []


def test_analyze_route_carries_claims_and_exact_sources(monkeypatch):
    source = passage()
    data = response(diagnostic_claims=[{
        "text": "Hypertension remains possible", "applies_to": "Hypertension",
        "supporting_evidence_ids": [source.id],
    }])
    fusion = fusion_with_response(data)

    class Clarifier:
        def process(self, raw):
            return PatientContext(raw_input=raw)

    class Orchestrator:
        def retrieve(self, context):
            return retrieval(source)

    class Ranker:
        def rank(self, *args):
            return []

    class Detector:
        def detect(self, *args):
            return []

    class Confidence:
        def evaluate(self, *args):
            return 0.5, "report"

    class Retry:
        max_retries = 0

        def should_retry(self, *args):
            return False

    monkeypatch.setattr(routes, "get_pipeline", lambda: {
        "clarifier": Clarifier(), "orchestrator": Orchestrator(), "ranker": Ranker(),
        "detector": Detector(), "fusion": fusion, "confidence": Confidence(),
        "retry": Retry(), "report": ReportGenerator(),
    })
    output = routes.analyze_case(routes.AnalyzeRequest(case_text="Adult with possible hypertension"))
    assert output["report"]["claims"][0]["supporting_evidence_ids"] == [source.id]
    assert output["report"]["source_passages"][0]["id"] == source.id
    assert output["report"]["claims"][0]["status"] == "unverified"
