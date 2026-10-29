"""Step 8 engineering checks; these fixtures do not assert clinical accuracy."""

import json
import sys
from datetime import date

import pytest

from backend.schemas.retrieval import GraphRetrievalResult
from evaluation.metrics import MODES, diagnostic_strata, provider_consistency, resolved_adjudications, review_id, score
from evaluation.run import RetrievalAblation, load_cases, main, validate_matrix, write_jsonl
from ingestion.authoritative_sources import build_passages, load_manifest


def _case():
    return {"case_id": "fixture", "case_text": "Documented hypertension",
            "reference_diagnosis_aliases": ["hypertension"],
            "expected_warning_types": ["amlodipine_allergy"]}


def _record(mode, passage):
    claim = {"claim_id": "warning-1", "claim_type": "medication_warning",
             "text": "Amlodipine sensitivity is a contraindication", "status": "supported",
             "supporting_evidence_ids": [passage.id]}
    return {"case_id": "fixture", "mode": mode, "status": "ok", "latency_ms": 12,
            "report": {"ranked_diagnoses": [{"diagnosis": "Hypertension"}],
                       "medication_safety": {"findings": [{"type": "amlodipine_allergy",
                                                            "verification_status": "supported"}]},
                       "source_passages": [passage.model_dump(mode="json")],
                       "claims": [claim]}}


def test_metrics_citation_integrity_warnings_abstention_and_review_gate():
    passage = next(item for entries in build_passages(load_manifest()).values()
                   for item, _ in entries if item.section.startswith("4 CONTRAINDICATIONS"))
    records = [_record(mode, passage) for mode in MODES]
    validate_matrix([_case()], records)
    result = score([_case()], records, [passage])
    for row in result["modes"].values():
        assert row["diagnostic_top1"]["value"] == 1
        assert row["diagnostic_top3"]["value"] == 1
        assert row["citation_validity"]["value"] == 1
        assert row["medication_warning_sensitivity"]["value"] == 1
        assert row["claim_support_accuracy"]["value"] is None
        assert row["unsafe_option_rate"]["value"] is None
    records[0]["report"]["source_passages"][0]["passage"] = "Forged passage"
    result = score([_case()], records, [passage])
    assert result["modes"]["llm_only"]["citation_validity"]["value"] == 0
    assert "invalid_citation:" in ",".join(result["case_errors"][0]["errors"])
    assert result["case_errors"][0]["predicted_diagnoses"] == ["Hypertension"]


def test_two_independent_reviewers_required_and_disagreement_retained():
    claim = {"claim_type": "treatment", "text": "A conditional option"}
    key = review_id("fixture", claim)
    first = {"review_id": key, "reviewer_id": "reviewer-a",
             "support_label": "supported", "option_safety_label": "safe"}
    assert resolved_adjudications([first]) == ({}, [])
    second = {**first, "reviewer_id": "reviewer-b", "support_label": "unsupported"}
    resolved, disagreements = resolved_adjudications([first, second])
    assert not resolved
    assert disagreements[0]["review_id"] == key
    with pytest.raises(ValueError, match="Duplicate reviewer"):
        resolved_adjudications([first, first])


def test_clinician_review_metrics_are_scored_only_after_agreement():
    claim = {"claim_id": "treatment-1", "claim_type": "treatment", "text": "Conditional option",
             "status": "supported", "supporting_evidence_ids": []}
    record = {"case_id": "fixture", "mode": "llm_only", "status": "ok", "latency_ms": 1,
              "report": {"ranked_diagnoses": [{"diagnosis": "Hypertension"}],
                         "medication_safety": {"findings": []}, "source_passages": [],
                         "claims": [claim]}}
    key = review_id("fixture", claim)
    ratings = [{"review_id": key, "reviewer_id": name, "support_label": "unsupported",
                "option_safety_label": "unsafe"} for name in ("a", "b")]
    unreviewed = score([_case()], [record], [])
    assert unreviewed["modes"]["llm_only"]["unsupported_claim_rate"]["value"] is None
    reviewed = score([_case()], [record], [], ratings)
    row = reviewed["modes"]["llm_only"]
    assert row["claim_support_accuracy"]["value"] == 0
    assert row["unsupported_claim_rate"]["value"] == 1
    assert row["unsafe_option_rate"]["value"] == 1


def test_retrieval_modes_hold_non_retrieval_pipeline_fixed():
    class Graph:
        def __init__(self):
            self.calls = 0

        def retrieve(self, context):
            self.calls += 1
            return GraphRetrievalResult(candidate_diseases=[{"name": "Hypertension"}], paths=[])

    class Vector:
        def __init__(self):
            self.calls = 0

        def retrieve(self, context):
            self.calls += 1
            return [{"id": "textbook"}]

        def retrieve_authoritative(self, context):
            return [], ["No pinned passage"]

    base = type("Base", (), {"graph_retriever": Graph(), "vector_retriever": Vector()})()
    blank = RetrievalAblation(base, "llm_only").retrieve(None)
    assert not blank.vector_results.evidence_items
    assert base.vector_retriever.calls == 0
    text = RetrievalAblation(base, "text_rag").retrieve(None)
    assert text.vector_results.evidence_items
    assert not text.graph_results.candidate_diseases
    combined = RetrievalAblation(base, "graph_text").retrieve(None)
    assert combined.graph_results.candidate_diseases
    assert base.graph_retriever.calls == 1


def test_replay_command_writes_versioned_provenance_and_case_errors(tmp_path, monkeypatch):
    case_path = tmp_path / "cases.json"
    case_path.write_text(json.dumps({"dataset_id": "test-only", "dataset_version": "1",
                                     "origin": "synthetic test-only", "cases": [_case()]}))
    records_path = tmp_path / "records.jsonl"
    records_path.write_text("".join(json.dumps({"case_id": "fixture", "mode": mode,
                                                "status": "error", "error_type": "FixtureFailure",
                                                "latency_ms": 5}) + "\n" for mode in MODES))
    output = tmp_path / "output"
    monkeypatch.setattr(sys, "argv", ["evaluation.run", "--cases", str(case_path),
                                      "--replay", str(records_path), "--output", str(output)])
    main()
    manifest = json.loads((output / "run_manifest.json").read_text())
    metrics = json.loads((output / "metrics.json").read_text())
    assert manifest["dataset_version"] == "1"
    assert manifest["clinical_validation"] is False
    assert manifest["source_manifest_sha256"]
    assert manifest["prompt_sha256"]
    assert metrics["clinical_validation"] is False
    assert metrics["modes"]["llm_only"]["failed_cases"] == 1
    assert metrics["modes"]["llm_only"]["diagnostic_top1"]["value"] is None
    assert len((output / "case_errors.jsonl").read_text().splitlines()) == 3


def test_frozen_cases_keep_reference_diagnoses_explicit():
    from evaluation.run import DEFAULT_CASES

    dataset, cases = load_cases(DEFAULT_CASES)
    assert dataset["dataset_version"] == "1.0.0"
    assert len(cases) == 6


def test_multidisease_pilot_hides_aliases_and_covers_four_strata():
    from pathlib import Path

    dataset, cases = load_cases(Path("evaluation/cases.multidisease-pilot.v1.json"))
    assert dataset["origin"].startswith("Hand-authored synthetic")
    assert len(cases) == 12
    assert {case["disease_stratum"] for case in cases} == {
        "hypertension", "chronic_asthma", "type_2_diabetes", "gord"}
    assert all(case["cohort"] == "diagnostic" and case["diagnosis_disclosed"] is False
               for case in cases)


def test_diagnostic_strata_keep_failure_denominators_and_macro_unavailable():
    cases = [
        {"case_id": "a", "cohort": "diagnostic", "disease_stratum": "alpha",
         "reference_diagnosis_aliases": ["A"]},
        {"case_id": "b", "cohort": "diagnostic", "disease_stratum": "beta",
         "reference_diagnosis_aliases": ["B"]},
    ]
    records = [{"case_id": case["case_id"], "mode": mode, "status": "ok",
                "report": {"ranked_diagnoses": [{"diagnosis": case["reference_diagnosis_aliases"][0]}]}}
               for mode in MODES for case in cases]
    records[-1] = {"case_id": "b", "mode": "graph_text", "status": "error"}
    result = diagnostic_strata(cases, records)
    assert result["llm_only"]["macro_top1"] == 1
    assert result["llm_only"]["diseases"]["alpha"]["top1"]["numerator"] == 1
    assert result["graph_text"]["diseases"]["beta"]["failed"] == 1
    assert result["graph_text"]["diseases"]["beta"]["top1"]["value"] is None
    assert result["graph_text"]["macro_top1"] is None


def test_result_writer_serializes_source_dates(tmp_path):
    path = tmp_path / "result.jsonl"
    write_jsonl(path, [{"document_date": date(2026, 1, 1)}])
    assert json.loads(path.read_text()) == {"document_date": "2026-01-01"}


def test_provider_mismatch_is_flagged_for_ablation_interpretation():
    records = [{"case_id": "fixture", "mode": mode, "status": "ok",
                "provider_trace": {"fusion": {"provider": provider, "model": provider}}}
               for mode, provider in zip(MODES, ("Gemini", "Cohere", "Gemini"))]
    result = provider_consistency([_case()], records)
    assert result["mismatched_case_ids"] == ["fixture"]
