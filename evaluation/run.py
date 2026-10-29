"""Run three retrieval ablations and generate auditable, bounded evaluation artifacts.

Usage: python -m evaluation.run --output evaluation/runs/my-run
       python -m evaluation.run --replay evaluation/runs/my-run/case_results.jsonl --output evaluation/runs/rescore
"""

import argparse
import hashlib
import inspect
import json
import platform
import random
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from backend.schemas.retrieval import GraphRetrievalResult, OrchestratorResult, VectorRetrievalResult
from evaluation.metrics import MODES, diagnostic_strata, review_id, score
from ingestion.authoritative_sources import DEFAULT_MANIFEST, build_passages, load_manifest


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = Path(__file__).with_name("cases.v1.json")
VALID_WARNINGS = {"amlodipine_allergy", "amlodipine_simvastatin", "allergy_status_unconfirmed"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_cases(path: Path) -> tuple[dict, list[dict]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases or not payload.get("dataset_version"):
        raise ValueError("Versioned evaluation case file is required")
    ids = [item.get("case_id") for item in cases]
    if any(not isinstance(item, str) or not item for item in ids) or len(set(ids)) != len(ids):
        raise ValueError("Evaluation case IDs must be unique and nonblank")
    for item in cases:
        if not isinstance(item.get("case_text"), str) or not item["case_text"].strip():
            raise ValueError(f"Case {item['case_id']} lacks case text")
        aliases = item.get("reference_diagnosis_aliases")
        if not isinstance(aliases, list) or not aliases or not all(isinstance(name, str) and name for name in aliases):
            raise ValueError(f"Case {item['case_id']} lacks reference diagnosis aliases")
        disclosed = item.get("diagnosis_disclosed", True)
        if not isinstance(disclosed, bool):
            raise ValueError(f"Case {item['case_id']} has invalid diagnosis_disclosed")
        contains_alias = any(name.casefold() in item["case_text"].casefold() for name in aliases)
        if disclosed and not contains_alias:
            raise ValueError(f"Case {item['case_id']} reference diagnosis is not explicit in its text")
        if not disclosed and contains_alias:
            raise ValueError(f"Case {item['case_id']} leaks a reference diagnosis alias in its text")
        warnings = item.get("expected_warning_types")
        if not isinstance(warnings, list) or any(name not in VALID_WARNINGS for name in warnings):
            raise ValueError(f"Case {item['case_id']} has unsupported warning labels")
    return payload, cases


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) + "\n")


class RetrievalAblation:
    """Keep clarification, synthesis, and verification fixed across retrieval modes."""

    def __init__(self, base, mode: str):
        self.base = base
        self.mode = mode

    def retrieve(self, context):
        empty_graph = GraphRetrievalResult(candidate_diseases=[], paths=[])
        if self.mode == "llm_only":
            return OrchestratorResult(graph_results=empty_graph, vector_results=VectorRetrievalResult())
        vector_items = self.base.vector_retriever.retrieve(context)
        passages, limitations = self.base.vector_retriever.retrieve_authoritative(context)
        graph = self.base.graph_retriever.retrieve(context) if self.mode == "graph_text" else empty_graph
        return OrchestratorResult(
            graph_results=graph, vector_results=VectorRetrievalResult(evidence_items=vector_items),
            source_passages=passages, source_retrieval_limitations=limitations,
        )


class FixedClarifier:
    def __init__(self, context):
        self.context = context

    def process(self, raw_text):
        if raw_text != self.context.raw_input:
            raise ValueError("Evaluation context can only be reused for its original case")
        return self.context.model_copy(deep=True)


def live_records(cases: list[dict], max_retries: int) -> tuple[list[dict], float]:
    from backend.agents.adaptive_retry import AdaptiveRetry
    from backend.api import routes

    initialized_at = time.perf_counter()
    base = routes.get_pipeline()
    initialization_ms = round((time.perf_counter() - initialized_at) * 1000, 1)
    original_state = routes.pipeline_state
    records = []
    try:
        for index, case in enumerate(cases):
            started = time.perf_counter()
            try:
                context = base["clarifier"].process(case["case_text"])
                clarification_ms = round((time.perf_counter() - started) * 1000, 1)
                clarification_provider = {
                    "provider": base["clarifier"].llm.last_provider,
                    "model": base["clarifier"].llm.last_model,
                }
            except Exception as exc:
                clarification_ms = round((time.perf_counter() - started) * 1000, 1)
                for mode in MODES:
                    records.append({"case_id": case["case_id"], "mode": mode,
                                    "status": "error", "error_type": type(exc).__name__,
                                    "latency_ms": clarification_ms, "clarification_ms": clarification_ms})
                continue
            order = MODES[index % len(MODES):] + MODES[:index % len(MODES)]
            for mode in order:
                services = dict(base)
                services["clarifier"] = FixedClarifier(context)
                services["orchestrator"] = RetrievalAblation(base["orchestrator"], mode)
                services["retry"] = AdaptiveRetry(max_retries=max_retries)
                routes.pipeline_state = services
                started = time.perf_counter()
                try:
                    result = routes.analyze_case(routes.AnalyzeRequest(case_text=case["case_text"]))
                    analysis_ms = round((time.perf_counter() - started) * 1000, 1)
                    records.append({
                        "case_id": case["case_id"], "mode": mode, "status": "ok",
                        "latency_ms": round(clarification_ms + analysis_ms, 1),
                        "clarification_ms": clarification_ms, "analysis_ms": analysis_ms,
                        "provider_trace": {
                            "clarifier": clarification_provider,
                            "fusion": {"provider": base["fusion"].llm.last_provider,
                                       "model": base["fusion"].llm.last_model},
                        },
                        "patient_context": result["patient_context"],
                        "retrieval": result["retrieval"], "report": result["report"],
                    })
                except Exception as exc:
                    analysis_ms = round((time.perf_counter() - started) * 1000, 1)
                    records.append({"case_id": case["case_id"], "mode": mode,
                                    "status": "error", "error_type": type(exc).__name__,
                                    "latency_ms": round(clarification_ms + analysis_ms, 1),
                                    "clarification_ms": clarification_ms, "analysis_ms": analysis_ms})
    finally:
        routes.pipeline_state = original_state
    return records, initialization_ms


def validate_matrix(cases: list[dict], records: list[dict]) -> None:
    expected = {(case["case_id"], mode) for case in cases for mode in MODES}
    actual = [(item.get("case_id"), item.get("mode")) for item in records]
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise ValueError("Run must contain exactly one result for every case and retrieval mode")


def review_artifacts(cases: list[dict], records: list[dict], sample_size: int,
                     seed: int) -> tuple[list[dict], list[dict]]:
    cases_by_id = {case["case_id"]: case for case in cases}
    packet_by_id = {}
    index = []
    for record in records:
        if record.get("status") != "ok":
            continue
        sources = {item["id"]: item for item in record["report"].get("source_passages", [])}
        for claim in record["report"].get("claims", []):
            key = review_id(record["case_id"], claim)
            ids = list(dict.fromkeys(claim.get("supporting_evidence_ids", []) +
                                     claim.get("conflicting_evidence_ids", []) +
                                     claim.get("unverified_evidence_ids", [])))
            packet_by_id.setdefault(key, {
                "review_id": key, "case_id": record["case_id"],
                "case_text": cases_by_id[record["case_id"]]["case_text"],
                "patient_context": record.get("patient_context"),
                "claim_type": claim.get("claim_type"), "claim_text": claim.get("text"),
                "applies_to": claim.get("applies_to"),
                "conditions": claim.get("conditions", []),
                "missing_checks": claim.get("missing_checks", []),
                "cited_passages": [sources[item] for item in ids if item in sources],
                "unresolved_citation_ids": [item for item in ids if item not in sources],
            })
            index.append({"review_id": key, "case_id": record["case_id"],
                          "mode": record["mode"], "claim_id": claim.get("claim_id"),
                          "system_status": claim.get("status")})
    packet = list(packet_by_id.values())
    random.Random(seed).shuffle(packet)
    return packet[:sample_size], index


def provenance(case_path: Path, dataset: dict, selected: list[dict],
               initialization_ms: float | None, replay_path: Path | None,
               adjudication_path: Path | None, max_retries: int) -> dict:
    from backend.agents.clarifier import ClinicalClarifier
    from backend.agents.fusion import ClinicalFusion
    from backend.services.llm_fallback import LLMFallback

    try:
        git_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip())
    except (OSError, subprocess.CalledProcessError):
        git_sha, dirty = None, None
    prompt_sources = {
        "clarifier_process": inspect.getsource(ClinicalClarifier.process),
        "fusion_prompt": inspect.getsource(ClinicalFusion._build_prompt),
        "fusion_generation": inspect.getsource(ClinicalFusion.fuse),
    }
    return {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "run_kind": "replay" if replay_path else (
            "live_exam_vignette_evaluation" if dataset.get("reference_kind") == "medqa_exam_answer"
            else "live_synthetic_evaluation"),
        "clinical_validation": False,
        "dataset_id": dataset["dataset_id"], "dataset_version": dataset["dataset_version"],
        "dataset_origin": dataset["origin"], "dataset_sha256": sha256(case_path),
        "case_ids": [item["case_id"] for item in selected],
        "retrieval_modes": list(MODES),
        "ablation_definition": {
            "llm_only": "No graph, vector, authoritative passages, DrugCentral, or web discovery",
            "text_rag": "Textbook vector and pinned guideline/label retrieval only",
            "graph_text": "Same text retrieval plus Neo4j graph candidates",
            "common": "Same extracted patient context, fusion, claim verifier, safety checks, and report generator",
        },
        "source_manifest_sha256": sha256(DEFAULT_MANIFEST),
        "source_documents": [{"document_id": item.document_id, "document_version": item.document_version,
                              "document_date": item.document_date, "updated_date": item.updated_date,
                              "sha256": item.sha256, "jurisdiction": item.jurisdiction}
                             for item in load_manifest().sources],
        "prompt_sha256": {name: hashlib.sha256(text.encode()).hexdigest()
                          for name, text in prompt_sources.items()},
        "models_in_fallback_order": LLMFallback.MODEL_IDS,
        "model_resolution_note": "openrouter/free does not pin its underlying model",
        "settings": {"max_retries": max_retries, "temperature": 0,
                     "review_sample_seed": 17,
                     "clarification_reused_across_modes": True,
                     "latency_definition": "context extraction plus per-mode analysis; model/embedding initialization excluded",
                     "web_and_drugcentral_disabled_for_ablation": True},
        "initialization_ms": initialization_ms,
        "replay_sha256": sha256(replay_path) if replay_path else None,
        "adjudications_sha256": sha256(adjudication_path) if adjudication_path else None,
        "git_sha": git_sha, "git_worktree_dirty": dirty,
        "python_version": platform.python_version(),
        "command": " ".join(sys.argv),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output", type=Path, default=None,
                        help="New output directory; defaults to ignored evaluation/runs/<UTC timestamp>")
    parser.add_argument("--replay", type=Path, help="Rescore captured case_results.jsonl without model calls")
    parser.add_argument("--adjudications", type=Path,
                        help="Clinician review JSONL; unresolved reviewer disagreements are excluded")
    parser.add_argument("--limit", type=int, default=0, help="First N cases for a smoke run; 0 runs all")
    parser.add_argument("--max-retries", type=int, default=0)
    parser.add_argument("--review-sample-size", type=int, default=30)
    args = parser.parse_args()
    if args.limit < 0 or args.max_retries < 0 or args.review_sample_size < 1:
        parser.error("Limit, retries, and review sample size must be nonnegative; sample size must be positive")
    dataset, cases = load_cases(args.cases)
    if args.limit:
        cases = cases[:args.limit]
    output = args.output or ROOT / "evaluation/runs" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if output.exists():
        parser.error(f"Output directory already exists: {output}")
    manifest = load_manifest()
    pinned = [item for entries in build_passages(manifest).values() for item, _ in entries]
    if any(case["case_text"] in source.passage for case in cases for source in pinned):
        raise ValueError("An evaluation case appears verbatim in the indexed source corpus")
    if args.replay:
        records = read_jsonl(args.replay)
        initialization_ms = None
    else:
        records, initialization_ms = live_records(cases, args.max_retries)
    validate_matrix(cases, records)
    adjudications = read_jsonl(args.adjudications) if args.adjudications else []
    if adjudications:
        available = {item["review_id"] for item in review_artifacts(
            cases, records, sample_size=10**9, seed=17)[1]}
        unknown = {item.get("review_id") for item in adjudications} - available
        if unknown:
            raise ValueError(f"Adjudications reference unknown review IDs: {sorted(unknown)}")
    metrics = score(cases, records, pinned, adjudications)
    packet, index = review_artifacts(cases, records, args.review_sample_size, seed=17)
    details = provenance(args.cases, dataset, cases, initialization_ms,
                         args.replay, args.adjudications, args.max_retries)
    output.mkdir(parents=True)
    (output / "run_manifest.json").write_text(json.dumps(details, indent=2, default=str) + "\n", encoding="utf-8")
    if dataset.get("reference_kind") == "medqa_exam_answer":
        reference_note = (
            "MedQA exam answer keys are not clinician-adjudicated patient diagnoses; "
            "exact top-k matches are generative vignette answer agreement, not clinical accuracy"
        )
    elif all(case.get("diagnosis_disclosed", True) for case in cases):
        reference_note = "All reference diagnoses are explicit in synthetic case text; top-k tests recognition only"
    else:
        reference_note = "Author-intended synthetic labels are not independently adjudicated; top-k is not clinical diagnostic accuracy"
    metric_payload = {
        "clinical_validation": False,
        "dataset_origin": dataset["origin"],
        "diagnostic_reference_note": reference_note,
        "clinical_adjudication_note": "Support and unsafe-option metrics require two agreeing independent reviewers",
        "reviewed_item_count": metrics["reviewed_item_count"],
        "provider_consistency": metrics["provider_consistency"],
        "modes": metrics["modes"],
        "diagnostic_strata": diagnostic_strata(cases, records),
    }
    (output / "metrics.json").write_text(json.dumps(metric_payload, indent=2) + "\n", encoding="utf-8")
    write_jsonl(output / "case_results.jsonl", records)
    write_jsonl(output / "case_errors.jsonl", metrics["case_errors"])
    write_jsonl(output / "review_packet_blinded.jsonl", packet)
    write_jsonl(output / "review_index_private.jsonl", index)
    write_jsonl(output / "review_disagreements.jsonl", metrics["review_disagreements"])
    print(json.dumps({"output": str(output),
                      "modes": {mode: {"successful_cases": row["successful_cases"],
                                       "failed_cases": row["failed_cases"]}
                                for mode, row in metrics["modes"].items()},
                      "review_items": len(packet)}, indent=2))


if __name__ == "__main__":
    main()
