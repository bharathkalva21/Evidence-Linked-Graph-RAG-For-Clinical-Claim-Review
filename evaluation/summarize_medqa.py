"""Export aggregate MedQA exam-pilot results without question or answer text."""

import argparse
import json
from collections import Counter
from pathlib import Path

from evaluation.metrics import MODES, diagnosis_key, fraction, wilson_interval
from evaluation.run import load_cases, read_jsonl, sha256, validate_matrix


ROOT = Path(__file__).resolve().parents[1]
SELECTION = ROOT / "evaluation/medqa_selection.v1.json"


def summarize(cases_path: Path, run_dir: Path) -> dict:
    dataset, cases = load_cases(cases_path)
    selection = json.loads(SELECTION.read_text(encoding="utf-8"))
    if dataset.get("reference_kind") != "medqa_exam_answer" or dataset.get("selection") != selection["selection"]:
        raise ValueError("Case file does not match the committed MedQA selection manifest")
    records_path = run_dir / "case_results.jsonl"
    records = read_jsonl(records_path)
    validate_matrix(cases, records)
    metrics_path = run_dir / "metrics.json"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    manifest_path = run_dir / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("dataset_sha256") != sha256(cases_path):
        raise ValueError("Run manifest does not match the case file")
    by_key = {(row["case_id"], row["mode"]): row for row in records}
    per_mode = {}
    for mode in MODES:
        steps = {}
        for step in ("step1", "step2&3"):
            selected = [case for case in cases if case["exam_step"] == step]
            complete = top1 = top3 = empty_ranked = 0
            for case in selected:
                record = by_key[(case["case_id"], mode)]
                if record.get("status") != "ok" or not isinstance(record.get("report"), dict):
                    continue
                complete += 1
                predicted = [diagnosis_key(item.get("diagnosis", ""))
                             for item in record["report"].get("ranked_diagnoses", [])
                             if item.get("diagnosis") and not item["diagnosis"].startswith("LLM synthesis unavailable")]
                empty_ranked += int(not predicted)
                key = diagnosis_key(case["reference_diagnosis_aliases"][0])
                top1 += int(bool(predicted[:1] and predicted[0] == key))
                top3 += int(key in predicted[:3])
            steps[step] = {
                "attempted": len(selected), "complete": complete,
                "failed": len(selected) - complete, "completed_without_ranked_diagnosis": empty_ranked,
                "top1": {**fraction(top1, complete, "No completed cases"),
                         "wilson_95": wilson_interval(top1, complete)},
                "top3": {**fraction(top3, complete, "No completed cases"),
                         "wilson_95": wilson_interval(top3, complete)},
            }
        mode_rows = [row for row in records if row["mode"] == mode]
        provider_counts = Counter(
            f"{row.get('provider_trace', {}).get('fusion', {}).get('provider', 'unknown')}:"
            f"{row.get('provider_trace', {}).get('fusion', {}).get('model', 'unknown')}"
            if row.get("status") == "ok" else "run_error"
            for row in mode_rows
        )
        overall = {}
        for rank in ("diagnostic_top1", "diagnostic_top3"):
            value = metrics["modes"][mode][rank]
            step_numerator = sum(item["top1" if rank == "diagnostic_top1" else "top3"]["numerator"]
                                 for item in steps.values())
            if step_numerator != value["numerator"]:
                raise ValueError(f"{mode} {rank} differs between per-step and main scorer")
            overall[rank] = {**value, "wilson_95": wilson_interval(value["numerator"], value["denominator"])}
        per_mode[mode] = {
            "metrics": metrics["modes"][mode],
            "overall_diagnosis_agreement": overall,
            "exam_step": steps,
            "completed_without_ranked_diagnosis": sum(item["completed_without_ranked_diagnosis"]
                                                      for item in steps.values()),
            "synthesis_provider_counts": dict(sorted(provider_counts.items())),
            "graph_candidates_total": sum(row.get("retrieval", {}).get("graph_candidates", 0) for row in mode_rows),
            "authoritative_passages_total": sum(row.get("retrieval", {}).get("authoritative_passages", 0) for row in mode_rows),
        }
    return {
        "snapshot_type": "exploratory_medqa_test_exam_vignette_pilot",
        "clinical_validation": False,
        "case_count": len(cases),
        "distinct_exam_answer_count": len({case["reference_diagnosis_aliases"][0] for case in cases}),
        "selection_manifest_sha256": sha256(SELECTION),
        "dataset_sha256": sha256(cases_path),
        "case_results_sha256": sha256(records_path),
        "metrics_sha256": sha256(metrics_path),
        "run_manifest_sha256": sha256(manifest_path),
        "run_created_utc": manifest["created_utc"],
        "run_git_sha": manifest["git_sha"],
        "run_git_worktree_dirty": manifest["git_worktree_dirty"],
        "source_manifest_sha256": manifest["source_manifest_sha256"],
        "reference_note": metrics["diagnostic_reference_note"],
        "provider_consistency": {
            "matched_case_count": len(metrics["provider_consistency"]["matched_case_ids"]),
            "mismatched_case_count": len(metrics["provider_consistency"]["mismatched_case_ids"]),
            "unknown_case_count": len(metrics["provider_consistency"]["unknown_case_ids"]),
        },
        "per_mode": per_mode,
        "limitations": [
            "Exam questions are not patient records or clinician-adjudicated reference diagnoses.",
            "Only strict normalized equality to one keyed option is scored; synonymous answers can count as misses.",
            "Public test questions may have appeared in provider training data.",
            "Treatment, warning, claim-support, and relevant-passage reference labels are unavailable.",
            "The pinned authoritative-source corpus covers only selected hypertension and amlodipine material.",
            "Provider fallback and unpinned openrouter/free underlying models limit retrieval-mode comparisons.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"Output already exists: {args.output}")
    payload = summarize(args.cases, args.run)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "case_count": payload["case_count"],
                      "top1": {mode: item["metrics"]["diagnostic_top1"] for mode, item in payload["per_mode"].items()}}, indent=2))


if __name__ == "__main__":
    main()
