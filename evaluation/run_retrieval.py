"""Score ranked pinned-source retrieval on frozen known-passage probes.

Usage: python -m evaluation.run_retrieval --output evaluation/runs/retrieval-probes-v1
       python -m evaluation.run_retrieval --replay evaluation/runs/retrieval-probes-v1/retrieval_records.jsonl --output evaluation/runs/retrieval-probes-v1-replay
"""

import argparse
import hashlib
import json
import subprocess
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from evaluation.metrics import percentile
from evaluation.retrieval_metrics import aggregate, score_query
from ingestion.authoritative_sources import COLLECTIONS, DEFAULT_MANIFEST, build_passages, load_manifest


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROBES = Path(__file__).with_name("retrieval_probes.v1.json")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_probes(path: Path) -> tuple[dict, list[dict], dict[str, str], dict[str, int]]:
    dataset = json.loads(path.read_text(encoding="utf-8"))
    if dataset.get("source_manifest_sha256") != sha256(DEFAULT_MANIFEST):
        raise ValueError("Probe labels do not match the pinned source manifest")
    grouped = build_passages(load_manifest())
    by_selector: dict[str, list[str]] = defaultdict(list)
    corpus_ids = set()
    corpus_counts = {}
    for kind, items in grouped.items():
        corpus_counts[kind] = len(items)
        for passage, _ in items:
            by_selector[f"{passage.document_id}::{passage.section}"].append(passage.id)
            corpus_ids.add(passage.id)
    probes = dataset.get("queries", [])
    if not probes or len({item.get("query_id") for item in probes}) != len(probes):
        raise ValueError("Nonempty probes with unique IDs are required")
    if dataset.get("ks") != [1, 3, 5, 10] or dataset.get("top_k_per_collection") != 5:
        raise ValueError("This frozen protocol expects K=1,3,5,10 and five hits per collection")
    selector_to_id = {}
    for probe in probes:
        if not isinstance(probe.get("query"), str) or not probe["query"].strip():
            raise ValueError(f"Blank query: {probe.get('query_id')}")
        selectors = set(probe.get("grades", {})) | {
            selector for options in probe.get("required_facts", {}).values() for selector in options}
        for selector in selectors:
            matches = by_selector.get(selector, [])
            if len(matches) != 1:
                raise ValueError(f"Source selector is absent or ambiguous: {selector}")
            selector_to_id[selector] = matches[0]
        grades = {selector_to_id[selector]: grade for selector, grade in probe["grades"].items()}
        facts = {name: [selector_to_id[selector] for selector in options]
                 for name, options in probe["required_facts"].items()}
        score_query([], grades, facts, dataset["ks"])
    return dataset, probes, selector_to_id, corpus_counts


def live_records(probes: list[dict], counts: dict[str, int], top_k: int) -> list[dict]:
    from backend.services.vector_retriever import VectorRetriever

    retriever = VectorRetriever()
    if not retriever.is_ready:
        raise RuntimeError("Vector retriever is unavailable")
    for kind, expected in counts.items():
        if expected:
            collection = COLLECTIONS[kind]
            actual = retriever.client.count(collection_name=collection, exact=True).count
            if actual != expected:
                raise RuntimeError(f"{collection} has {actual} points; expected {expected} pinned passages")
    records = []
    for probe in probes:
        started = time.perf_counter()
        passages, limitations = retriever.retrieve_authoritative_query(probe["query"], top_k=top_k)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        if limitations or len(passages) != top_k * sum(bool(count) for count in counts.values()):
            raise RuntimeError(f"Incomplete retrieval for {probe['query_id']}: {limitations}; {len(passages)} passages")
        records.append({"query_id": probe["query_id"],
                        "ordered_source_ids": [passage.id for passage in passages],
                        "latency_ms": elapsed_ms, "limitations": limitations})
    return records


def score_records(dataset: dict, probes: list[dict], selector_to_id: dict[str, str],
                  records: list[dict], corpus_ids: set[str]) -> dict:
    if len(records) != len(probes) or {row.get("query_id") for row in records} != {
            probe["query_id"] for probe in probes}:
        raise ValueError("Exactly one retrieval record is required per probe")
    by_id = {record["query_id"]: record for record in records}
    if len(by_id) != len(records):
        raise ValueError("Duplicate retrieval records")
    scored = []
    for probe in probes:
        record = by_id[probe["query_id"]]
        ids = record["ordered_source_ids"]
        if not isinstance(ids, list) or not set(ids) <= corpus_ids:
            raise ValueError(f"Unrecognized retrieved source ID for {probe['query_id']}")
        grades = {selector_to_id[selector]: grade for selector, grade in probe["grades"].items()}
        facts = {name: [selector_to_id[selector] for selector in options]
                 for name, options in probe["required_facts"].items()}
        scored.append({"query_id": probe["query_id"], "retrieval_latency_ms": record.get("latency_ms"),
                       **score_query(ids, grades, facts, dataset["ks"])})
    latencies = [row["latency_ms"] for row in records if isinstance(row.get("latency_ms"), (int, float))]
    return {"query_count": len(probes), "completed_queries": len(records), "per_query": scored,
            "aggregate": aggregate(scored, dataset["ks"]),
            "retrieval_latency_ms": {"median": percentile(latencies, 0.5),
                                     "p95": percentile(latencies, 0.95),
                                     "max": max(latencies) if latencies else None},
            "unavailable_metrics": {
                "generation_faithfulness": "Requires independent claim-to-source support judgments; source identity is insufficient",
                "answer_relevance": "Requires a reference question-answer judgment set",
                "answer_completeness": "Requires an independently defined complete answer or fact checklist for generated reports",
                "cost_per_query": "Retriever token/cost accounting is not instrumented; local vector-query monetary cost is not recorded",
                "clinical_task_completion": "No clinician workflow or patient-outcome reference labels",
            },
            "definitions": {
                "binary_relevance": "Grade 2 direct-answer passages; grade 1 related passages do not count for P/Recall/Hit/MRR",
                "precision_at_k": "Direct-answer passages in actual top K / K; missing slots count as nonrelevant",
                "recall_at_k": "Direct-answer passages in actual top K / all developer-judged direct-answer passages in the 26-passage corpus",
                "hit_rate_at_k": "Queries with at least one direct-answer passage in top K / all queries",
                "mrr_at_k": "Mean reciprocal rank of first direct-answer passage within top K; zero when absent",
                "ndcg_at_k": "Mean DCG/ideal DCG using gains 2^grade-1 and log2(rank+1) discount",
                "context_relevance": "Direct-answer passages / all passages in the complete retrieved context; equivalent to binary precision at context length",
                "context_recall": "Developer-listed required facts with at least one linked passage retrieved / all listed required facts",
                "rank_order": "The production retriever concatenates guideline top five, then drug-label top five; there is no cross-collection score merge",
            }}


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probes", type=Path, default=DEFAULT_PROBES)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--replay", type=Path, help="Saved retrieval_records.jsonl; no model or Qdrant call")
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"Output already exists: {args.output}")
    dataset, probes, selector_to_id, counts = load_probes(args.probes)
    corpus_ids = {passage.id for items in build_passages(load_manifest()).values() for passage, _ in items}
    if args.replay:
        records = [json.loads(line) for line in args.replay.read_text(encoding="utf-8").splitlines() if line.strip()]
    else:
        records = live_records(probes, counts, dataset["top_k_per_collection"])
    metrics = score_records(dataset, probes, selector_to_id, records, corpus_ids)
    try:
        git_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip())
    except (OSError, subprocess.CalledProcessError):
        git_sha, dirty = None, None
    manifest = {"created_utc": datetime.now(timezone.utc).isoformat(),
                "run_kind": "replay" if args.replay else "live_known_passage_retrieval_probe",
                "clinical_validation": False,
                "annotation_status": dataset["annotation_status"],
                "probe_sha256": sha256(args.probes),
                "source_manifest_sha256": sha256(DEFAULT_MANIFEST),
                "corpus_counts": counts,
                "embedder": "pritamdeka/S-PubMedBert-MS-MARCO",
                "collection_order": list(COLLECTIONS),
                "top_k_per_collection": dataset["top_k_per_collection"],
                "git_sha": git_sha, "git_worktree_dirty": dirty,
                "replay_source_sha256": sha256(args.replay) if args.replay else None}
    args.output.mkdir(parents=True)
    write_jsonl(args.output / "retrieval_records.jsonl", records)
    (args.output / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    (args.output / "run_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "query_count": len(probes),
                      "hit_at_5": metrics["aggregate"]["at_k"]["5"]["hit_rate"],
                      "context_recall": metrics["aggregate"]["context_recall"]}, indent=2))


if __name__ == "__main__":
    main()
