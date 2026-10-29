"""Explicit-denominator engineering metrics; no clinical labels are inferred."""

import hashlib
import json
import math
import re
from collections import defaultdict

from backend.schemas.evidence import SourcePassage


MODES = ("llm_only", "text_rag", "graph_text")
LABEL_WARNING_TYPES = {"amlodipine_allergy", "amlodipine_simvastatin"}


def fraction(numerator: int, denominator: int, missing_reason: str) -> dict:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": round(numerator / denominator, 4) if denominator else None,
        "unavailable_reason": None if denominator else missing_reason,
    }


def wilson_interval(numerator: int, denominator: int) -> list[float] | None:
    """Descriptive 95% binomial interval for the observed case sample."""
    if not denominator:
        return None
    z = 1.959963984540054
    p = numerator / denominator
    z2 = z * z
    center = (p + z2 / (2 * denominator)) / (1 + z2 / denominator)
    width = z * math.sqrt(p * (1 - p) / denominator + z2 / (4 * denominator**2)) / (1 + z2 / denominator)
    return [round(max(0.0, center - width), 4), round(min(1.0, center + width), 4)]


def diagnostic_strata(cases: list[dict], records: list[dict]) -> dict:
    """Score reference labels by declared stratum without hiding run failures."""
    if not all(case.get("cohort") == "diagnostic" and case.get("disease_stratum") for case in cases):
        return {}
    rows_by_key = {(row.get("case_id"), row.get("mode")): row for row in records}
    diseases = sorted({case["disease_stratum"] for case in cases})
    output = {}
    for mode in MODES:
        strata = {}
        for disease in diseases:
            selected = [case for case in cases if case["disease_stratum"] == disease]
            complete = top1 = top3 = 0
            for case in selected:
                row = rows_by_key.get((case["case_id"], mode), {})
                report = row.get("report")
                if row.get("status") != "ok" or not isinstance(report, dict):
                    continue
                complete += 1
                accepted = {diagnosis_key(name) for name in case["reference_diagnosis_aliases"]}
                predicted = [diagnosis_key(item.get("diagnosis", ""))
                             for item in report.get("ranked_diagnoses", [])
                             if item.get("diagnosis") and not item["diagnosis"].startswith("LLM synthesis unavailable")]
                top1 += int(bool(predicted[:1] and predicted[0] in accepted))
                top3 += int(any(name in accepted for name in predicted[:3]))
            strata[disease] = {
                "attempted": len(selected), "complete": complete, "failed": len(selected) - complete,
                "top1": {**fraction(top1, complete, "No completed cases"),
                         "wilson_95": wilson_interval(top1, complete)},
                "top3": {**fraction(top3, complete, "No completed cases"),
                         "wilson_95": wilson_interval(top3, complete)},
            }
        complete_strata = [row for row in strata.values() if row["complete"]]
        macro_available = len(complete_strata) == len(diseases)
        output[mode] = {
            "diseases": strata,
            "macro_top1": round(sum(row["top1"]["value"] for row in complete_strata) / len(diseases), 4)
                          if macro_available else None,
            "macro_top3": round(sum(row["top3"]["value"] for row in complete_strata) / len(diseases), 4)
                          if macro_available else None,
            "macro_unavailable_reason": None if macro_available else "At least one disease has no completed cases",
        }
    return output


def review_id(case_id: str, claim: dict) -> str:
    identity = [case_id, claim.get("claim_type"), claim.get("text"), claim.get("applies_to"),
                claim.get("conditions", []), claim.get("missing_checks", []),
                sorted(claim.get("supporting_evidence_ids", []) +
                       claim.get("conflicting_evidence_ids", []) +
                       claim.get("unverified_evidence_ids", []))]
    value = json.dumps(identity, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return "review_" + hashlib.sha256(value.encode()).hexdigest()[:20]


def diagnosis_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower), 1)


def resolved_adjudications(rows: list[dict]) -> tuple[dict[str, dict], list[dict]]:
    """Use only unanimous labels; disagreements stay visible for reconciliation."""
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if not row.get("review_id") or not row.get("reviewer_id"):
            raise ValueError("Adjudications require review_id and reviewer_id")
        if row.get("support_label") not in {"supported", "unsupported", "uncertain"}:
            raise ValueError("Invalid support_label in adjudications")
        if row.get("option_safety_label") not in {"safe", "unsafe", "uncertain"}:
            raise ValueError("Invalid option_safety_label in adjudications")
        grouped[row["review_id"]].append(row)
    resolved = {}
    disagreements = []
    for key, ratings in grouped.items():
        reviewer_ids = [item["reviewer_id"] for item in ratings]
        if len(reviewer_ids) != len(set(reviewer_ids)):
            raise ValueError(f"Duplicate reviewer for {key}")
        if len(reviewer_ids) < 2:
            continue
        labels = {(item.get("support_label", "uncertain"),
                   item.get("option_safety_label", "uncertain")) for item in ratings}
        if len(labels) == 1:
            support, safety = next(iter(labels))
            resolved[key] = {"support_label": support, "option_safety_label": safety,
                             "reviewer_count": len(ratings)}
        else:
            disagreements.append({"review_id": key, "ratings": ratings})
    return resolved, disagreements


def provider_consistency(cases: list[dict], records: list[dict]) -> dict:
    """Flag comparisons where fallback selected a different synthesis model."""
    by_case = defaultdict(list)
    for record in records:
        by_case[record.get("case_id")].append(record)
    matched, mismatched, unknown = [], [], []
    for case in cases:
        case_id = case["case_id"]
        rows = by_case[case_id]
        if len(rows) != len(MODES) or any(row.get("status") != "ok" for row in rows):
            unknown.append(case_id)
            continue
        providers = [(row.get("provider_trace", {}).get("fusion", {}).get("provider"),
                      row.get("provider_trace", {}).get("fusion", {}).get("model")) for row in rows]
        if any(provider is None or model is None for provider, model in providers):
            unknown.append(case_id)
        elif len(set(providers)) == 1:
            matched.append(case_id)
        else:
            mismatched.append(case_id)
    return {"matched_case_ids": matched, "mismatched_case_ids": mismatched,
            "unknown_case_ids": unknown,
            "interpretation": "Retrieval effects are confounded when synthesis providers differ across modes"}


def score(cases: list[dict], records: list[dict], pinned: list[SourcePassage],
          adjudications: list[dict] | None = None) -> dict:
    pinned_by_id = {item.id: item for item in pinned}
    reviewed, disagreements = resolved_adjudications(adjudications or [])
    cases_by_id = {case["case_id"]: case for case in cases}
    results = {}
    errors = []
    for mode in MODES:
        selected = [item for item in records if item.get("mode") == mode]
        top1 = top3 = diagnosis_total = 0
        citation_valid = citation_total = 0
        warnings_found = warning_total = verified_found = label_warning_total = 0
        warning_false_positives = warning_negative_cases = 0
        claim_total = abstained = 0
        support_correct = support_decided = unsupported_supported = supported_reviewed = 0
        unsafe_options = reviewed_options = reviewed_claims = 0
        successful = 0
        latencies = []
        for record in selected:
            case_id = record.get("case_id")
            case = cases_by_id.get(case_id)
            if case is None:
                errors.append({"mode": mode, "case_id": case_id, "errors": ["unknown_case_id"]})
                continue
            latencies.append(record.get("latency_ms", 0))
            if record.get("status") != "ok" or not isinstance(record.get("report"), dict):
                errors.append({"mode": mode, "case_id": case_id,
                               "errors": ["run_failed", record.get("error_type", "unknown_error")]})
                continue
            successful += 1
            report = record["report"]
            case_errors = []
            aliases = {diagnosis_key(name) for name in case["reference_diagnosis_aliases"]}
            predicted = [diagnosis_key(item.get("diagnosis", ""))
                         for item in report.get("ranked_diagnoses", [])
                         if not item.get("diagnosis", "").startswith("LLM synthesis unavailable")]
            diagnosis_total += 1
            if predicted[:1] and predicted[0] in aliases:
                top1 += 1
            else:
                case_errors.append("top1_miss")
            if any(item in aliases for item in predicted[:3]):
                top3 += 1
            else:
                case_errors.append("top3_miss")

            findings = report.get("medication_safety", {}).get("findings", [])
            observed = {item.get("type") for item in findings}
            verified = {item.get("type") for item in findings
                        if item.get("verification_status") == "supported"}
            expected = set(case["expected_warning_types"])
            warning_total += len(expected)
            warnings_found += len(expected & observed)
            label_expected = expected & LABEL_WARNING_TYPES
            label_warning_total += len(label_expected)
            verified_found += len(label_expected & verified)
            missed = sorted(expected - observed)
            if missed:
                case_errors.append("missed_warning:" + ",".join(missed))
            if not expected:
                warning_negative_cases += 1
                if observed & LABEL_WARNING_TYPES:
                    warning_false_positives += 1
                    case_errors.append("unexpected_label_warning")

            source_map = {}
            for data in report.get("source_passages", []):
                try:
                    source = SourcePassage.model_validate(data)
                    source_map[source.id] = source
                except (ValueError, TypeError):
                    continue
            invalid_ids = []
            for claim in report.get("claims", []):
                claim_total += 1
                if claim.get("status") == "unverified":
                    abstained += 1
                for source_id in (claim.get("supporting_evidence_ids", []) +
                                  claim.get("conflicting_evidence_ids", []) +
                                  claim.get("unverified_evidence_ids", [])):
                    citation_total += 1
                    if source_id in source_map and source_map[source_id] == pinned_by_id.get(source_id):
                        citation_valid += 1
                    else:
                        invalid_ids.append(source_id)
                rating = reviewed.get(review_id(case_id, claim))
                if not rating:
                    continue
                reviewed_claims += 1
                label = rating["support_label"]
                status = claim.get("status")
                if status in {"supported", "conflicting"} and label in {"supported", "unsupported"}:
                    support_decided += 1
                    support_correct += int((status == "supported") == (label == "supported"))
                if status == "supported" and label in {"supported", "unsupported"}:
                    supported_reviewed += 1
                    unsupported_supported += int(label == "unsupported")
                    if label == "unsupported":
                        case_errors.append("unsupported_supported_claim")
                if claim.get("claim_type") == "treatment" and rating["option_safety_label"] in {"safe", "unsafe"}:
                    reviewed_options += 1
                    unsafe_options += int(rating["option_safety_label"] == "unsafe")
                    if rating["option_safety_label"] == "unsafe":
                        case_errors.append("unsafe_treatment_option")
            if invalid_ids:
                case_errors.append("invalid_citation:" + ",".join(sorted(set(invalid_ids))))
            if case_errors:
                errors.append({"mode": mode, "case_id": case_id, "errors": case_errors,
                               "reference_diagnosis_aliases": case["reference_diagnosis_aliases"],
                               "predicted_diagnoses": [item.get("diagnosis") for item in report.get("ranked_diagnoses", [])],
                               "expected_warning_types": sorted(expected),
                               "observed_warning_types": sorted(name for name in observed if isinstance(name, str))})

        results[mode] = {
            "case_count": len(selected), "successful_cases": successful,
            "failed_cases": len(selected) - successful,
            "diagnostic_top1": fraction(top1, diagnosis_total, "No successful cases with reference diagnoses"),
            "diagnostic_top3": fraction(top3, diagnosis_total, "No successful cases with reference diagnoses"),
            "citation_validity": fraction(citation_valid, citation_total, "No citation IDs emitted"),
            "claim_support_accuracy": fraction(support_correct, support_decided,
                                               "Requires adjudicated supported/conflicting claims"),
            "unsupported_claim_rate": fraction(unsupported_supported, supported_reviewed,
                                               "Requires adjudicated supported claims"),
            "medication_warning_sensitivity": fraction(warnings_found, warning_total,
                                                       "No expected warning types in successful cases"),
            "verified_label_warning_sensitivity": fraction(verified_found, label_warning_total,
                                                            "No expected label warnings in successful cases"),
            "label_warning_false_positive_case_rate": fraction(warning_false_positives, warning_negative_cases,
                                                               "No warning-negative cases"),
            "unsafe_option_rate": fraction(unsafe_options, reviewed_options,
                                           "Requires clinician-reviewed treatment safety labels"),
            "claim_abstention_rate": fraction(abstained, claim_total, "No claims emitted"),
            "reviewed_claims": reviewed_claims,
            "latency_ms": {"median": percentile(latencies, 0.5),
                           "p95": percentile(latencies, 0.95),
                           "max": round(max(latencies), 1) if latencies else None},
        }
    return {"modes": results, "case_errors": errors, "review_disagreements": disagreements,
            "provider_consistency": provider_consistency(cases, records),
            "reviewed_item_count": len(reviewed)}
