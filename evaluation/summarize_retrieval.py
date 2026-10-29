"""Publish a text-free, checked snapshot of a frozen retrieval-probe run."""

import argparse
import json
from pathlib import Path

from evaluation.run_retrieval import DEFAULT_PROBES, load_probes, score_records, sha256
from ingestion.authoritative_sources import build_passages, load_manifest


def summarize(probes_path: Path, run_dir: Path, replay_metrics_path: Path | None) -> dict:
    dataset, probes, selector_to_id, counts = load_probes(probes_path)
    records_path = run_dir / "retrieval_records.jsonl"
    records = [json.loads(line) for line in records_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    corpus_ids = {passage.id for items in build_passages(load_manifest()).values() for passage, _ in items}
    rescored = score_records(dataset, probes, selector_to_id, records, corpus_ids)
    metrics_path = run_dir / "metrics.json"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    if metrics != rescored:
        raise ValueError("Saved retrieval metrics do not match a fresh score of the ordered source IDs")
    manifest_path = run_dir / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["probe_sha256"] != sha256(probes_path) or manifest["corpus_counts"] != counts:
        raise ValueError("Run provenance differs from the frozen probes or current pinned corpus")
    replay_identical = None
    if replay_metrics_path:
        replay_identical = replay_metrics_path.read_bytes() == metrics_path.read_bytes()
        if not replay_identical:
            raise ValueError("Replay metrics differ from live metrics")
    return {
        "snapshot_type": "developer_judged_known_passage_retrieval_probe",
        "clinical_validation": False,
        "annotation_status": dataset["annotation_status"],
        "dataset_id": dataset["dataset_id"],
        "dataset_version": dataset["dataset_version"],
        "probe_sha256": sha256(probes_path),
        "retrieval_records_sha256": sha256(records_path),
        "metrics_sha256": sha256(metrics_path),
        "run_manifest_sha256": sha256(manifest_path),
        "source_manifest_sha256": manifest["source_manifest_sha256"],
        "run_created_utc": manifest["created_utc"],
        "run_git_sha": manifest["git_sha"],
        "run_git_worktree_dirty": manifest["git_worktree_dirty"],
        "corpus_counts": counts,
        "embedder": manifest["embedder"],
        "collection_order": manifest["collection_order"],
        "top_k_per_collection": manifest["top_k_per_collection"],
        "replay_metrics_byte_identical": replay_identical,
        "metrics": metrics,
        "limitations": [
            "Ten developer-authored known-passage queries were derived from the same 26-passages corpus being searched.",
            "Relevance grades and required facts were not independently or clinically adjudicated.",
            "Recall is bounded to judged passages in the pinned corpus, not all relevant medical literature.",
            "The actual context order concatenates five guideline hits before five label hits; it is not a global score rank.",
            "The probe does not evaluate textbook or graph retrieval, generated-answer faithfulness, or clinical decisions.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probes", type=Path, default=DEFAULT_PROBES)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--replay-metrics", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"Output already exists: {args.output}")
    payload = summarize(args.probes, args.run, args.replay_metrics)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output),
                      "hit_at_5": payload["metrics"]["aggregate"]["at_k"]["5"]["hit_rate"],
                      "replay_identical": payload["replay_metrics_byte_identical"]}, indent=2))


if __name__ == "__main__":
    main()
