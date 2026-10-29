"""Create a label-blinded packet for independent clinician review of synthetic cases."""

import argparse
import hashlib
import json
from pathlib import Path

from evaluation.run_med_safety import DEFAULT_CASES, FROZEN_CASES_SHA256, sha256
from ingestion.authoritative_sources import build_passages, load_manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"Output exists: {args.output}")
    if sha256(args.cases) != FROZEN_CASES_SHA256:
        parser.error("Case file differs from frozen version")
    cases = json.loads(args.cases.read_text(encoding="utf-8"))["cases"]
    labels = [passage for items in build_passages(load_manifest()).values()
              for passage, _ in items if passage.source_type == "drug_label"
              and ("4 CONTRAINDICATIONS" in passage.section or
                   "7.2 Impact of Amlodipine on Other Drugs" in passage.section)]
    if not labels:
        parser.error("Pinned label warning passages unavailable")
    label_sections = [{"source_id": passage.id, "section": passage.section,
                       "url": str(passage.url), "passage": passage.passage} for passage in labels]
    ordered = sorted(cases, key=lambda case: hashlib.sha256(case["case_id"].encode()).hexdigest())
    args.output.mkdir(parents=True)
    with (args.output / "review_packet.jsonl").open("w", encoding="utf-8") as stream:
        for index, case in enumerate(ordered, 1):
            row = {"review_id": f"safety_review_{index:03d}",
                   "case_text": case["case_text"],
                   "question": "If amlodipine is being considered, which warning(s) and verification status are justified?",
                   "pinned_label_sections": label_sections}
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (args.output / "private_review_index.jsonl").open("w", encoding="utf-8") as stream:
        for index, case in enumerate(ordered, 1):
            row = {"review_id": f"safety_review_{index:03d}", "case_id": case["case_id"],
                   "developer_expected_warning_types": case["expected_warning_types"],
                   "developer_expected_supported_warning_types": case["expected_supported_warning_types"]}
            stream.write(json.dumps(row) + "\n")
    print(json.dumps({"output": str(args.output), "review_items": len(ordered),
                      "instruction": "Give reviewers only review_packet.jsonl; retain private_review_index.jsonl"}))


if __name__ == "__main__":
    main()
