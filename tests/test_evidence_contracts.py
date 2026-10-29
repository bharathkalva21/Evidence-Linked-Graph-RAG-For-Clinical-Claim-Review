from datetime import date

import pytest
from pydantic import ValidationError

from backend.schemas.evidence import SourcePassage
from backend.schemas.report import ClinicalClaim, ClinicalReport
from backend.schemas.retrieval import GraphRetrievalResult, OrchestratorResult, VectorRetrievalResult


def source(**overrides):
    fields = {
        "source_type": "guideline",
        "source_name": "Example clinical guideline",
        "publisher": "Example Society",
        "document_id": "example-guideline-1",
        "document_version": "2026-01",
        "title": "Example guideline",
        "document_date": date(2026, 1, 1),
        "url": "https://example.org/guideline",
        "jurisdiction": "global",
        "section": "Recommendation 2",
        "span_start": 100,
        "span_end": 145,
        "passage": "Consider the option only after diagnosis is confirmed.",
    }
    fields.update(overrides)
    return SourcePassage(**fields)


def report(**overrides):
    fields = {
        "disclaimer": "For clinician review",
        "case_summary": "Example case",
        "ranked_diagnoses": [],
        "missing_information": [],
        "conflicts": [],
        "overall_confidence": 0.0,
        "limitations": [],
        "references": [],
    }
    fields.update(overrides)
    return ClinicalReport(**fields)


def test_source_id_is_stable_and_detects_mismatched_identity():
    original = source()
    assert source().id == original.id
    assert source(document_version="2026-02").id != original.id
    assert source(span_start=101).id != original.id
    assert source(passage="A revised recommendation.").id != original.id
    assert SourcePassage.model_validate(original.model_dump()).id == original.id

    with pytest.raises(ValidationError, match="Source ID does not match"):
        source(id="src_incorrect")


def test_authoritative_source_needs_traceable_metadata():
    with pytest.raises(ValidationError, match="URL and document date"):
        source(url=None)
    with pytest.raises(ValidationError, match="span_end"):
        source(span_end=100)


def test_supported_claim_requires_resolvable_non_graph_source():
    passage = source()
    claim = ClinicalClaim(
        claim_id="treatment-1",
        claim_type="treatment",
        text="Conditional treatment option",
        status="supported",
        conditions=["Diagnosis confirmed"],
        supporting_evidence_ids=[passage.id],
    )
    assert report(claims=[claim], source_passages=[passage]).claims[0].status == "supported"

    with pytest.raises(ValidationError, match="unavailable source passages"):
        report(claims=[claim])

    graph_passage = source(source_type="graph_relation", url=None, document_date=None)
    graph_claim = claim.model_copy(update={"supporting_evidence_ids": [graph_passage.id]})
    with pytest.raises(ValidationError, match="only by graph relations"):
        report(claims=[graph_claim], source_passages=[graph_passage])


def test_unverified_claim_records_reason_and_old_reports_still_parse():
    with pytest.raises(ValidationError, match="unverified claim needs a reason"):
        ClinicalClaim(claim_id="warning-1", claim_type="medication_warning", text="Unknown allergy risk", status="unverified")

    legacy_report = report()
    serialized = legacy_report.model_dump(mode="json")
    assert serialized["ranked_diagnoses"] == []
    assert serialized["references"] == []
    assert serialized["claims"] == []
    assert serialized["source_passages"] == []
    assert ClinicalReport.model_validate(serialized).claims == []

    retrieval = OrchestratorResult(
        graph_results=GraphRetrievalResult(candidate_diseases=[], paths=[]),
        vector_results=VectorRetrievalResult(),
    )
    assert retrieval.source_passages == []
