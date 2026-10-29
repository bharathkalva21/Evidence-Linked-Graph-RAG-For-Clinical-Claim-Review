"""Aggregate exam-score export must not include source question or answer text."""

import json

from evaluation import summarize_medqa
from evaluation.run import sha256, write_jsonl


def test_exam_summary_scores_steps_and_excludes_raw_content(tmp_path, monkeypatch):
    cases = [
        {"case_id": "one", "case_text": "A patient with an unexplained presentation.",
         "reference_diagnosis_aliases": ["Answer A"], "diagnosis_disclosed": False,
         "expected_warning_types": [], "exam_step": "step1"},
        {"case_id": "two", "case_text": "A second patient with another presentation.",
         "reference_diagnosis_aliases": ["Answer B"], "diagnosis_disclosed": False,
         "expected_warning_types": [], "exam_step": "step2&3"},
    ]
    selection = {"selected_zero_based_source_indices": [1, 2]}
    case_file = tmp_path / "cases.json"
    case_file.write_text(json.dumps({"dataset_id": "test", "dataset_version": "1",
                                    "reference_kind": "medqa_exam_answer", "selection": selection,
                                    "cases": cases}), encoding="utf-8")
    selection_file = tmp_path / "selection.json"
    selection_file.write_text(json.dumps({"selection": selection}), encoding="utf-8")
    monkeypatch.setattr(summarize_medqa, "SELECTION", selection_file)
    run = tmp_path / "run"
    run.mkdir()
    rows = []
    for mode in ("llm_only", "text_rag", "graph_text"):
        for case, diagnosis in zip(cases, ("Answer A", "Other")):
            rows.append({"case_id": case["case_id"], "mode": mode, "status": "ok",
                         "report": {"ranked_diagnoses": [{"diagnosis": diagnosis}]},
                         "retrieval": {"graph_candidates": 0, "authoritative_passages": 0},
                         "provider_trace": {"fusion": {"provider": "test", "model": "test"}}})
    write_jsonl(run / "case_results.jsonl", rows)
    (run / "metrics.json").write_text(json.dumps({
        "modes": {mode: {"diagnostic_top1": {"numerator": 1, "denominator": 2},
                         "diagnostic_top3": {"numerator": 1, "denominator": 2}}
                  for mode in ("llm_only", "text_rag", "graph_text")},
        "diagnostic_reference_note": "exam", "provider_consistency": {
            "matched_case_ids": ["one", "two"], "mismatched_case_ids": [], "unknown_case_ids": []}}), encoding="utf-8")
    (run / "run_manifest.json").write_text(json.dumps({
        "dataset_sha256": sha256(case_file), "created_utc": "2026-10-13T00:00:00Z",
        "git_sha": "test", "git_worktree_dirty": False, "source_manifest_sha256": "test"}), encoding="utf-8")
    result = summarize_medqa.summarize(case_file, run)
    assert result["per_mode"]["llm_only"]["exam_step"]["step1"]["top1"]["numerator"] == 1
    assert result["per_mode"]["llm_only"]["exam_step"]["step2&3"]["top1"]["numerator"] == 0
    text = json.dumps(result)
    assert "Answer A" not in text and "unexplained presentation" not in text
