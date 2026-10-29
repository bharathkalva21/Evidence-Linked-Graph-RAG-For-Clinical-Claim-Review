"""Normalize model claim proposals into traceable, explicitly unverified claims."""

import hashlib
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.schemas.evidence import SourcePassage
from backend.schemas.patient import PatientContext
from backend.schemas.report import ClinicalClaim


class ClaimProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_type: Literal["diagnosis", "investigation", "treatment"]
    text: str = Field(min_length=1)
    applies_to: str | None = None
    conditions: list[str] = Field(default_factory=list)
    missing_checks: list[str] = Field(default_factory=list)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    conflicting_evidence_ids: list[str] = Field(default_factory=list)
    unverified_evidence_ids: list[str] = Field(default_factory=list)

    @field_validator("text", "applies_to")
    @classmethod
    def nonblank(cls, value):
        if value is not None and not value.strip():
            raise ValueError("Claim text and applicable diagnosis cannot be blank")
        return value.strip() if value is not None else None

    @field_validator("conditions", "missing_checks", "supporting_evidence_ids",
                     "conflicting_evidence_ids", "unverified_evidence_ids")
    @classmethod
    def nonblank_list(cls, value):
        if any(not item.strip() for item in value):
            raise ValueError("Claim lists cannot contain blank values")
        return value

    @model_validator(mode="after")
    def condition_required(self):
        if self.claim_type in {"investigation", "treatment"} and not self.applies_to:
            raise ValueError("Investigation and treatment claims must name the applicable condition")
        if self.claim_type == "treatment" and not self.conditions:
            raise ValueError("Treatment claim needs explicit conditions")
        if self.claim_type == "treatment" and re.match(r"^(?:start|prescribe|administer|give|take|use)\b", self.text, re.I):
            raise ValueError("Treatment option must not be an imperative instruction")
        return self


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def normalize_claims(
    proposals: list[ClaimProposal],
    source_passages: list[SourcePassage],
    context: PatientContext,
) -> list[ClinicalClaim]:
    """Preserve candidate evidence buckets without declaring clinical support yet."""
    citable = {source.id: source for source in source_passages
               if source.source_type in {"guideline", "drug_label", "study"}}
    claims = []
    seen_ids = set()
    for proposal in proposals:
        buckets = {
            "supporting": [], "conflicting": [], "unverified": [],
        }
        rejected = []
        for key, ids in (
            ("supporting", proposal.supporting_evidence_ids),
            ("conflicting", proposal.conflicting_evidence_ids),
            ("unverified", proposal.unverified_evidence_ids),
        ):
            for source_id in ids:
                if source_id in citable:
                    buckets[key].append(source_id)
                else:
                    rejected.append(source_id)
        buckets = {key: _unique(ids) for key, ids in buckets.items()}
        # An ID assigned incompatible roles needs review, not a forced choice.
        repeated = set(buckets["supporting"]) & set(buckets["conflicting"])
        repeated |= set(buckets["supporting"]) & set(buckets["unverified"])
        repeated |= set(buckets["conflicting"]) & set(buckets["unverified"])
        if repeated:
            for key in buckets:
                buckets[key] = [source_id for source_id in buckets[key] if source_id not in repeated]
            buckets["unverified"].extend(sorted(repeated))

        conditions = _unique(proposal.conditions)
        missing_checks = _unique(proposal.missing_checks)
        if proposal.claim_type == "treatment":
            condition = f"Diagnosis or condition confirmed: {proposal.applies_to}"
            if not any(item.casefold() == condition.casefold() for item in conditions):
                conditions.insert(0, condition)
            missing_checks = _unique(missing_checks + context.missing_information)

        reason_parts = ["Independent source support and patient applicability checks are pending"]
        if not any(buckets.values()):
            reason_parts.append("No available authoritative passage was linked")
        if rejected:
            reason_parts.append("Rejected unavailable or non-authoritative citation IDs: " + ", ".join(_unique(rejected)))
        if repeated:
            reason_parts.append("The same passage was assigned conflicting evidence roles")
        if missing_checks:
            reason_parts.append("Required checks remain: " + "; ".join(missing_checks))

        identity = json.dumps([proposal.claim_type, proposal.text, proposal.applies_to,
                               conditions, missing_checks, {key: sorted(ids) for key, ids in buckets.items()}],
                              sort_keys=True, ensure_ascii=False)
        claim_id = "claim_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
        if claim_id in seen_ids:
            continue
        seen_ids.add(claim_id)
        claims.append(ClinicalClaim(
            claim_id=claim_id, claim_type=proposal.claim_type,
            text=proposal.text, applies_to=proposal.applies_to,
            status="unverified", conditions=conditions, missing_checks=missing_checks,
            supporting_evidence_ids=buckets["supporting"],
            conflicting_evidence_ids=buckets["conflicting"],
            unverified_evidence_ids=buckets["unverified"],
            rejected_evidence_ids=_unique(rejected),
            unverified_reason="; ".join(reason_parts),
        ))
    return claims
