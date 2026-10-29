"""Exercise valid controls and one-factor provenance corruptions without an LLM."""

import argparse
import hashlib
import json
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from backend.schemas.patient import PatientContext
from backend.schemas.report import ClinicalClaim
from backend.services.claim_verifier import ClaimVerifier
from ingestion.authoritative_sources import DEFAULT_MANIFEST, build_passages, checked_bytes, load_manifest


ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def proposal(cited_id: str) -> ClinicalClaim:
    return ClinicalClaim(claim_id="provenance_probe", claim_type="treatment",
                         text="Review a treatment option", status="unverified",
                         applies_to="Hypertension", supporting_evidence_ids=[cited_id],
                         unverified_reason="Semantic support requires clinician review")


def verification(verifier: ClaimVerifier, supplied: list, cited_id: str) -> dict:
    context = PatientContext(raw_input="Synthetic provenance probe", age=60,
                             allergy_status="no_known_allergies", medication_list_status="none_reported")
    result = verifier.verify(context, [proposal(cited_id)], supplied)
    return {"trusted_ids": [source.id for source in result.trusted_passages],
            "validated_citations": result.evidence_completeness["validated_citations"],
            "invalid_citations": result.evidence_completeness["invalid_citations"],
            "claim_status": result.claims[0].status}


def run_checks() -> tuple[list[dict], dict]:
    manifest = load_manifest()
    pinned = [source for items in build_passages(manifest).values() for source, _ in items]
    verifier = ClaimVerifier(pinned)
    records = []
    for source in pinned:
        valid = verification(verifier, [source], source.id)
        records.append({"document_id": source.document_id, "source_id": source.id,
                        "mutation": "valid_control", "passed":
                        valid["trusted_ids"] == [source.id] and valid["validated_citations"] == 1
                        and valid["invalid_citations"] == 0 and valid["claim_status"] == "unverified"})

        invented = "src_invented_" + source.id.removeprefix("src_")
        changed = {
            "invented_citation_id": ([source], invented),
            "wrong_document_version": ([source.model_copy(update={"document_version": "wrong-version"})], source.id),
            "modified_passage_text": ([source.model_copy(update={"passage": source.passage + " CORRUPTED"})], source.id),
            "wrong_source_type": ([source.model_copy(update={"source_type": "other"})], source.id),
            "forged_retrieved_id": ([source.model_copy(update={"id": invented})], invented),
        }
        for mutation, (supplied, cited_id) in changed.items():
            observed = verification(verifier, supplied, cited_id)
            citation_rejected = observed["validated_citations"] == 0 and observed["invalid_citations"] == 1
            invalid_source_excluded = (mutation == "invented_citation_id" or not observed["trusted_ids"])
            records.append({"document_id": source.document_id, "source_id": source.id,
                            "mutation": mutation, "passed": citation_rejected and invalid_source_excluded,
                            "observed": observed if not (citation_rejected and invalid_source_excluded) else None})

    for entry in manifest.sources:
        if entry.retired:
            continue
        changed_entry = entry.model_copy(update={"sha256": "0" * 64})
        try:
            checked_bytes(changed_entry)
        except ValueError as exc:
            passed = "checksum mismatch" in str(exc)
        else:
            passed = False
        records.append({"document_id": entry.document_id, "source_id": None,
                        "mutation": "wrong_snapshot_sha256", "passed": passed})
    counts = Counter(row["mutation"] for row in records)
    successes = Counter(row["mutation"] for row in records if row["passed"])
    summary = {mutation: {"passed": successes[mutation], "attempted": total}
               for mutation, total in sorted(counts.items())}
    return records, summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"Output exists: {args.output}")
    records, by_mutation = run_checks()
    git_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    git_dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip())
    summary = {
        "test": "B: pinned-source provenance tampering",
        "clinical_validation": False,
        "source_manifest_sha256": sha256(DEFAULT_MANIFEST),
        "git": {"sha": git_sha, "dirty": git_dirty},
        "run_created_utc": datetime.now(timezone.utc).isoformat(),
        "valid_controls": by_mutation.pop("valid_control"),
        "mutations": by_mutation,
        "rejection_total": {
            "passed": sum(item["passed"] for item in by_mutation.values()),
            "attempted": sum(item["attempted"] for item in by_mutation.values()),
        },
        "interpretation": "Identity and checksum rejection only; semantic claim support is not adjudicated",
    }
    args.output.mkdir(parents=True)
    with (args.output / "records.jsonl").open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, sort_keys=True) + "\n")
    summary["records_sha256"] = sha256(args.output / "records.jsonl")
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "summary": summary}, indent=2))


if __name__ == "__main__":
    main()
