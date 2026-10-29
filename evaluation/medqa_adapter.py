"""Create a frozen, diagnosis-only MedQA exam-vignette set from a local test split.

The generated JSON contains copyrighted question stems and answer keys. Keep it in
the Git-ignored evaluation/runs directory; commit only the selection protocol.
"""

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "datasets/literature/MedQA/MedQA-USMLE/questions/US/test.jsonl"
DEFAULT_OUTPUT = ROOT / "evaluation/runs/medqa-us-diagnosis-v1/cases.json"
SOURCE_SHA256 = "cfa75cbcc53c29b023752b0a395ff49d8202121041392735ae44771a5ec734a3"
SELECTION_SEED = "cdss-medqa-diagnosis-v1"
PROMPT = re.compile(
    r"(?i)(?:what|which)(?:\s+of\s+the\s+following)?\s+is\s+the\s+most\s+likely"
    r"\s+diagnosis\s*\?\s*[\"\u201d]?\s*$"
)
QUOTAS = {"step1": 12, "step2&3": 24}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_cases(source: Path, quotas: dict[str, int] = QUOTAS) -> dict:
    source_hash = sha256(source)
    if source_hash != SOURCE_SHA256:
        raise ValueError(f"Expected MedQA US test split SHA-256 {SOURCE_SHA256}; found {source_hash}")
    rows = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
    candidates: dict[str, list[tuple[int, str, str]]] = {key: [] for key in quotas}
    exclusions = Counter()
    for index, row in enumerate(rows):
        question = row.get("question", "").strip()
        match = PROMPT.search(question)
        if not match:
            exclusions["not_exact_diagnosis_prompt"] += 1
            continue
        answer = row.get("answer", "").strip()
        stem = question[:match.start()].strip()
        if not answer or row.get("options", {}).get(row.get("answer_idx")) != answer:
            exclusions["answer_choice_mismatch"] += 1
        elif len(stem) < 100:
            exclusions["stem_under_100_characters"] += 1
        elif answer.casefold() in stem.casefold():
            exclusions["literal_answer_in_stem"] += 1
        elif row.get("meta_info") not in candidates:
            exclusions["unrecognized_exam_step"] += 1
        else:
            candidates[row["meta_info"]].append((index, stem, answer))
    selected = []
    for step, quota in quotas.items():
        pool = candidates[step]
        if len(pool) < quota:
            raise ValueError(f"{step} has only {len(pool)} eligible cases; requested {quota}")
        ranked = sorted(pool, key=lambda item: hashlib.sha256(
            f"{SELECTION_SEED}:{step}:{item[0]}".encode("ascii")
        ).hexdigest())
        selected.extend((step, *item) for item in ranked[:quota])
    selected.sort(key=lambda item: item[1])
    return {
        "dataset_id": "medqa-us-test-diagnosis-exam-pilot",
        "dataset_version": "1.0.0",
        "origin": "MedQA USMLE public test split; exam-vignette answer keys, not patient records or clinician-adjudicated reference diagnoses",
        "reference_kind": "medqa_exam_answer",
        "scope": "Diagnosis-prompt exam vignettes; answer options and final question withheld from model input",
        "selection": {
            "source_path": "datasets/literature/MedQA/MedQA-USMLE/questions/US/test.jsonl",
            "source_sha256": source_hash,
            "source_row_count": len(rows),
            "source_url": "https://github.com/jind11/MedQA",
            "eligibility": "Exact terminal most-likely-diagnosis prompt; answer equals keyed option; stem >=100 characters; no literal answer in stem; recognized exam step",
            "selection_seed": SELECTION_SEED,
            "quota_by_step": quotas,
            "eligible_by_step": {step: len(items) for step, items in candidates.items()},
            "excluded_reason_counts": dict(sorted(exclusions.items())),
            "selected_zero_based_source_indices": [index for _, index, _, _ in selected],
        },
        "cases": [
            {
                "case_id": f"medqa-us-test-{index:04d}",
                "cohort": "diagnostic",
                "disease_stratum": "mixed_exam_diagnoses",
                "exam_step": step,
                "source_row_index_zero_based": index,
                "diagnosis_disclosed": False,
                "case_text": stem,
                "reference_diagnosis_aliases": [answer],
                "expected_warning_types": [],
            }
            for step, index, stem, answer in selected
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"Output already exists: {args.output}")
    dataset = make_cases(args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(dataset, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "case_count": len(dataset["cases"]),
                      "selected_source_indices": dataset["selection"]["selected_zero_based_source_indices"]}, indent=2))


if __name__ == "__main__":
    main()
