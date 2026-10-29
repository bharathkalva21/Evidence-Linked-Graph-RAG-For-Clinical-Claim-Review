"""The exam adapter must freeze selection without leaking the answer to the model."""

import hashlib
import json

import pytest

from evaluation import medqa_adapter
from evaluation.run import load_cases


def test_exam_selection_is_reproducible_and_answer_hidden(tmp_path, monkeypatch):
    rows = [
        {"question": "A 42-year-old patient has a long clinical history of fever and an unusual rash, with several months of unexplained joint pain and fatigue. "
                     "Which of the following is the most likely diagnosis?",
         "answer": "Diagnosis A", "answer_idx": "A", "options": {"A": "Diagnosis A", "B": "Diagnosis B"},
         "meta_info": "step1"},
        {"question": "A 51-year-old patient has a long clinical history of chest discomfort and recent dyspnea, with worsening symptoms during daily exercise over six weeks. "
                     "What is the most likely diagnosis?",
         "answer": "Diagnosis C", "answer_idx": "B", "options": {"A": "Diagnosis D", "B": "Diagnosis C"},
         "meta_info": "step2&3"},
        {"question": "A 29-year-old patient already has Diagnosis E and a long documented clinical history, with symptoms recurring during the last several months. "
                     "What is the most likely diagnosis?",
         "answer": "Diagnosis E", "answer_idx": "A", "options": {"A": "Diagnosis E"},
         "meta_info": "step1"},
    ]
    source = tmp_path / "test.jsonl"
    source.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    monkeypatch.setattr(medqa_adapter, "SOURCE_SHA256", hashlib.sha256(source.read_bytes()).hexdigest())
    first = medqa_adapter.make_cases(source, {"step1": 1, "step2&3": 1})
    assert first == medqa_adapter.make_cases(source, {"step1": 1, "step2&3": 1})
    assert first["selection"]["excluded_reason_counts"]["literal_answer_in_stem"] == 1
    assert first["selection"]["selected_zero_based_source_indices"] == [0, 1]
    for case in first["cases"]:
        assert "most likely diagnosis" not in case["case_text"].casefold()
        assert case["reference_diagnosis_aliases"][0] not in case["case_text"]
    output = tmp_path / "cases.json"
    output.write_text(json.dumps(first), encoding="utf-8")
    _, loaded = load_cases(output)
    assert len(loaded) == 2


def test_exam_source_hash_is_required(tmp_path):
    source = tmp_path / "test.jsonl"
    source.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Expected MedQA US test split SHA-256"):
        medqa_adapter.make_cases(source)
