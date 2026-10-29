"""Evidence contracts shared by retrieval, synthesis, and reporting."""

import hashlib
import json
from datetime import date
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator


SourceType = Literal["guideline", "drug_label", "study", "textbook", "graph_relation", "other"]


class SourcePassage(BaseModel):
    """A traceable span of a versioned source document."""

    id: str = ""
    source_type: SourceType
    source_name: str
    publisher: str
    document_id: str
    document_version: str
    title: str
    document_date: Optional[date] = None
    updated_date: Optional[date] = None
    url: Optional[HttpUrl] = None
    jurisdiction: Optional[str] = None
    section: str
    span_start: int = Field(ge=0)
    span_end: int = Field(gt=0)
    passage: str

    @field_validator("source_name", "publisher", "document_id", "document_version", "title", "section", "passage")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Source metadata and passage must not be blank")
        return value.strip()

    @model_validator(mode="after")
    def validate_provenance(self) -> "SourcePassage":
        if self.span_end <= self.span_start:
            raise ValueError("Source span_end must be greater than span_start")
        if self.source_type in ("guideline", "drug_label", "study"):
            if not self.url or not self.document_date:
                raise ValueError("Guidelines, drug labels, and studies need a URL and document date")

        identity = json.dumps(
            [
                self.publisher,
                self.document_id,
                self.document_version,
                self.section,
                self.span_start,
                self.span_end,
                hashlib.sha256(self.passage.encode("utf-8")).hexdigest(),
            ],
            separators=(",", ":"),
            ensure_ascii=False,
        )
        expected_id = "src_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
        if self.id and self.id != expected_id:
            raise ValueError("Source ID does not match its document, span, and passage")
        self.id = expected_id
        return self


class EvidenceItem(BaseModel):
    # id remains the legacy retrieval-item ID. New claims cite source_passage_id.
    id: str
    source_type: str
    source_name: str
    title: Optional[str] = None
    text: str
    score: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)
    supports: List[str] = Field(default_factory=list)
    contradicts: List[str] = Field(default_factory=list)
    source_passage_id: Optional[str] = None
