"""Run the frozen amlodipine safety set through two bounded, LLM-free paths."""

import argparse
import hashlib
import json
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from backend.agents.conflict_detector import ConflictDetector
from backend.schemas.patient import LinkedEntity, PatientContext
from backend.schemas.report import ClinicalClaim
from backend.services.claim_verifier import ClaimVerifier
from backend.services.patient_fact_extractor import extract_safety_facts
from evaluation.metrics import wilson_interval
from ingestion.authoritative_sources import DEFAULT_MANIFEST, build_passages, load_manifest


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = ROOT / "evaluation/med_safety_cases.v1.json"
FROZEN_CASES_SHA256 = "ed00878d7a5a62377e525f51794f46ac35389cfdf120526935d31a554f126992"
SUPPORTED_TYPES = {"amlodipine_allergy", "amlodipine_simvastatin"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_state() -> dict:
    return {
        "sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip()),
    }


def structured_context(case: dict) -> PatientContext:
    return PatientContext(raw_input=case["case_text"], age=60, hypertension_scope=True,
                          hypertension_confirmed=True, **case["structured_facts"])


def extracted_context(case: dict) -> PatientContext:
    facts = extract_safety_facts(case["case_text"], {})
    allergies = [LinkedEntity(text=name, entity_type="allergy", source_phrase=quote,
                              extraction_certainty="explicit")
                 for name, quote in facts["allergy_mentions"]]
    return PatientContext(
        raw_input=case["case_text"], allergy_status=facts["allergy_status"],
        medication_list_status=facts["medication_list_status"],
        medication_statements=facts["medication_statements"], allergies=allergies,
        hypertension_scope=facts["hypertension_scope"],
        hypertension_confirmed=facts["hypertension_confirmed"],
        missing_information=facts["missing_information"], safety_flags=facts["safety_flags"],
    )


def evaluate_case(case: dict, path: str, pinned: list, label_passages: list) -> dict:
    context = structured_context(case) if path == "structured" else extracted_context(case)
    proposal = ClinicalClaim(
        claim_id="fixed_amlodipine_option", claim_type="treatment",
        text="Consider amlodipine for confirmed hypertension", status="unverified",
        applies_to="Hypertension", unverified_reason="Pending independent clinical review",
    )
    checked = ClaimVerifier(pinned).verify(context, [proposal], label_passages)
    findings, warning_claims = ConflictDetector().detect_medication_safety(
        context, checked.trusted_passages, checked.claims)
    actual = {item["type"] for item in findings}
    supported = {item["type"] for item in findings if item["verification_status"] == "supported"}
    expected = set(case["expected_warning_types"])
    expected_supported = set(case["expected_supported_warning_types"])
    actual_current = sorted({item.name.casefold() for item in context.medication_statements
                             if item.status == "current" and item.extraction_certainty == "explicit"})
    intended_current = sorted({item["name"].casefold() for item in
                               case["structured_facts"]["medication_statements"]
                               if item["status"] == "current"})
    treatment_status = checked.claims[0].status
    return {
        "case_id": case["case_id"], "stratum": case["stratum"], "path": path,
        "expected_warning_types": sorted(expected), "actual_warning_types": sorted(actual),
        "expected_supported_warning_types": sorted(expected_supported),
        "actual_supported_warning_types": sorted(supported),
        "allergy_status_expected": case["structured_facts"]["allergy_status"],
        "allergy_status_actual": context.allergy_status,
        "medication_status_expected": case["structured_facts"]["medication_list_status"],
        "medication_status_actual": context.medication_list_status,
        "current_medications_expected": intended_current,
        "current_medications_actual": actual_current,
        "expected_treatment_conflict": case["expected_treatment_conflict"],
        "actual_treatment_conflict": treatment_status == "conflicting",
        "treatment_status": treatment_status,
        "supported_warning_claim_count": len(warning_claims),
        "trusted_label_passage_count": len(checked.trusted_passages),
        "unexpected_warnings": sorted(actual - expected),
        "missed_warnings": sorted(expected - actual),
        "unexpected_supported_warnings": sorted(supported - expected_supported),
        "missed_supported_warnings": sorted(expected_supported - supported),
    }


def proportion(numerator: int, denominator: int) -> dict:
    return {"numerator": numerator, "denominator": denominator,
            "value": round(numerator / denominator, 4) if denominator else None,
            "wilson_95": wilson_interval(numerator, denominator)}


def score(records: list[dict], cases: list[dict]) -> dict:
    result = {}
    by_path = defaultdict(list)
    for record in records:
        by_path[record["path"]].append(record)
    for path, rows in sorted(by_path.items()):
        if len(rows) != len(cases) or len({r["case_id"] for r in rows}) != len(cases):
            raise ValueError("Safety run must have exactly one row per case and path")
        expected_count = sum(len(r["expected_warning_types"]) for r in rows)
        observed_count = sum(len(r["actual_warning_types"]) for r in rows)
        true_positive = sum(len(set(r["expected_warning_types"]) & set(r["actual_warning_types"]))
                            for r in rows)
        supported_negatives = sum(len(SUPPORTED_TYPES - set(r["expected_supported_warning_types"]))
                                  for r in rows)
        false_supported = sum(len(r["unexpected_supported_warnings"]) for r in rows)
        unknown = [r for r in rows if r["stratum"] in {"unknown_allergy", "conflicting_allergy"}]
        abstained = sum("allergy_status_unconfirmed" in r["actual_warning_types"] and
                        "allergy_status_unconfirmed" not in r["actual_supported_warning_types"] and
                        "amlodipine_allergy" not in r["actual_supported_warning_types"]
                        for r in unknown)
        strata = {}
        for stratum in sorted({r["stratum"] for r in rows}):
            selected = [r for r in rows if r["stratum"] == stratum]
            exact = sum(r["expected_warning_types"] == r["actual_warning_types"] and
                        r["expected_supported_warning_types"] == r["actual_supported_warning_types"]
                        for r in selected)
            strata[stratum] = {"cases": len(selected), "exact_warning_and_support_cases": exact,
                               "missed_warning_events": sum(len(r["missed_warnings"]) for r in selected),
                               "unexpected_warning_events": sum(len(r["unexpected_warnings"]) for r in selected)}
        result[path] = {
            "case_count": len(rows),
            "warning_precision": proportion(true_positive, observed_count),
            "warning_recall": proportion(true_positive, expected_count),
            "false_support_rate": proportion(false_supported, supported_negatives),
            "unknown_allergy_abstention": proportion(abstained, len(unknown)),
            "allergy_status_match": proportion(sum(r["allergy_status_expected"] == r["allergy_status_actual"]
                                                   for r in rows), len(rows)),
            "medication_status_match": proportion(sum(r["medication_status_expected"] ==
                                                       r["medication_status_actual"] for r in rows), len(rows)),
            "current_medication_match": proportion(sum(r["current_medications_expected"] ==
                                                        r["current_medications_actual"] for r in rows), len(rows)),
            "treatment_conflict_match": proportion(sum(r["expected_treatment_conflict"] ==
                                                       r["actual_treatment_conflict"] for r in rows), len(rows)),
            "strata": strata,
            "failure_case_ids": [r["case_id"] for r in rows if
                                 (r["expected_warning_types"] != r["actual_warning_types"] or
                                  r["expected_supported_warning_types"] != r["actual_supported_warning_types"] or
                                  r["allergy_status_expected"] != r["allergy_status_actual"] or
                                  r["medication_status_expected"] != r["medication_status_actual"] or
                                  r["current_medications_expected"] != r["current_medications_actual"] or
                                  r["expected_treatment_conflict"] != r["actual_treatment_conflict"])],
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"Output exists: {args.output}")
    if sha256(args.cases) != FROZEN_CASES_SHA256:
        parser.error("Frozen case file SHA-256 differs; use a newly versioned protocol for changes")
    dataset = json.loads(args.cases.read_text(encoding="utf-8"))
    cases = dataset["cases"]
    if len(cases) != 108 or dataset["label_status"].startswith("Clinician"):
        parser.error("Expected 108 developer-labeled synthetic cases")
    pinned = [source for items in build_passages(load_manifest()).values() for source, _ in items]
    label_passages = [source for source in pinned if source.source_type == "drug_label"]
    records = [evaluate_case(case, path, pinned, label_passages)
               for path in ("structured", "text_extractor") for case in cases]
    summary = {
        "test": "A: synthetic amlodipine medication-safety challenge",
        "clinical_validation": False,
        "label_status": dataset["label_status"],
        "case_sha256": sha256(args.cases), "source_manifest_sha256": sha256(DEFAULT_MANIFEST),
        "git": git_state(), "run_created_utc": datetime.now(timezone.utc).isoformat(),
        "paths": score(records, cases),
        "limits": ["Fixed amlodipine proposal; no LLM generation or live source retrieval",
                   "Text path runs deterministic safety-fact extractor with empty model hints, not /analyze",
                   "Developer-authored labels from the same narrow label/rule scope; clinician review pending",
                   "Wilson intervals describe this constructed challenge set, not patient prevalence or clinical safety"],
    }
    args.output.mkdir(parents=True)
    with (args.output / "records.jsonl").open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, sort_keys=True) + "\n")
    summary["records_sha256"] = sha256(args.output / "records.jsonl")
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "metrics": summary["paths"]}, indent=2))


if __name__ == "__main__":
    main()
