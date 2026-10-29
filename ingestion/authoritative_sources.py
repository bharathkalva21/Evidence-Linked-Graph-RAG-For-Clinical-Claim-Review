"""Pin, parse, and index a small authoritative clinical source set."""

import argparse
import hashlib
import json
import re
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field, HttpUrl, field_validator
from qdrant_client.models import Distance, PointStruct, VectorParams

from backend.config import settings
from backend.schemas.evidence import SourcePassage


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = PROJECT_ROOT / "sources/hypertension/manifest.json"
ALLOWED_HOSTS = {"www.nice.org.uk", "dailymed.nlm.nih.gov"}
COLLECTIONS = {"guideline": settings.VECTOR_COLLECTION_GUIDELINES,
               "drug_label": settings.VECTOR_COLLECTION_DRUG_LABELS}
SPL_NS = "{urn:hl7-org:v3}"


class SourceEntry(BaseModel):
    source_type: Literal["guideline", "drug_label"]
    source_name: str = Field(min_length=1)
    publisher: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    document_version: str = Field(min_length=1)
    title: str = Field(min_length=1)
    document_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    updated_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    url: HttpUrl
    canonical_url: HttpUrl | None = None
    download_url: HttpUrl | None = None
    jurisdiction: str = Field(min_length=1)
    reuse_terms: str = Field(min_length=1)
    clinical_scope: str = Field(min_length=1)
    retired: bool
    local_path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    format: Literal["nice_recommendations_html", "dailymed_spl_xml"]
    sections: list[str] = Field(min_length=1)

    @field_validator("url", "canonical_url", "download_url")
    @classmethod
    def official_host_only(cls, url):
        if url and (url.scheme != "https" or url.host not in ALLOWED_HOSTS):
            raise ValueError("Citation and download URLs must use an approved official host")
        return url

    @field_validator("local_path")
    @classmethod
    def restricted_local_path(cls, value):
        path = (PROJECT_ROOT / value).resolve()
        if not path.is_relative_to(PROJECT_ROOT / "datasets/authoritative"):
            raise ValueError("Source file must be under ignored datasets/authoritative")
        return value


class SourceManifest(BaseModel):
    clinical_area: str = Field(min_length=1)
    manifest_version: str = Field(min_length=1)
    review_status: str = Field(min_length=1)
    sources: list[SourceEntry] = Field(min_length=1)


def load_manifest(path: Path = DEFAULT_MANIFEST) -> SourceManifest:
    manifest = SourceManifest.model_validate(json.loads(path.read_text(encoding="utf-8")))
    identities = [(s.document_id, s.document_version) for s in manifest.sources]
    if len(identities) != len(set(identities)):
        raise ValueError("Duplicate document/version in source manifest")
    return manifest


def checked_bytes(entry: SourceEntry) -> bytes:
    path = PROJECT_ROOT / entry.local_path
    data = path.read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    if actual != entry.sha256:
        raise ValueError(f"Source checksum mismatch for {entry.document_id}: {actual}")
    return data


def fetch_sources(manifest: SourceManifest) -> None:
    """Fetch only a byte-for-byte match to the pinned manifest."""
    for entry in manifest.sources:
        if entry.retired:
            continue
        url = str(entry.download_url or entry.url)
        response = requests.get(url, timeout=40)
        response.raise_for_status()
        if urlparse(response.url).hostname not in ALLOWED_HOSTS:
            raise ValueError(f"Source redirected away from an approved official host: {entry.document_id}")
        actual = hashlib.sha256(response.content).hexdigest()
        if actual != entry.sha256:
            raise ValueError(f"Remote source changed for {entry.document_id}: {actual}; review and pin a new version")
        path = PROJECT_ROOT / entry.local_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(response.content)


def _passage(entry: SourceEntry, section: str, text: str, start: int, url: str) -> SourcePassage:
    return SourcePassage(
        source_type=entry.source_type, source_name=entry.source_name,
        publisher=entry.publisher, document_id=entry.document_id,
        document_version=entry.document_version, title=entry.title,
        document_date=entry.document_date, updated_date=entry.updated_date,
        url=url, jurisdiction=entry.jurisdiction, section=section,
        span_start=start, span_end=start + len(text), passage=text,
    )


def _clean(text: str) -> str:
    return " ".join(text.split())


def parse_nice(entry: SourceEntry, data: bytes) -> list[SourcePassage]:
    soup = BeautifulSoup(data, "html.parser")
    passages = []
    for number in entry.sections:
        anchor = "ng136-" + number.replace(".", "_")
        article = soup.find("article", id=anchor)
        body = article.select_one(".recommendation__body") if article else None
        if not body:
            raise ValueError(f"Missing NICE recommendation {number}")
        text = _clean(body.get_text(" ", strip=True))
        if not text:
            raise ValueError(f"Empty NICE recommendation {number}")
        passages.append(_passage(entry, f"Recommendation {number}", text, 0, f"{entry.url}#{anchor}"))
    return passages


def _label_sections(section: ET.Element, parent_title: str = ""):
    title = _clean("".join(section.find(SPL_NS + "title").itertext())) if section.find(SPL_NS + "title") is not None else ""
    label = title or parent_title
    text_element = section.find(SPL_NS + "text")
    if text_element is not None:
        text = _clean(" ".join(text_element.itertext()))
        if text:
            yield label, text
    for child in section.findall(f"{SPL_NS}component/{SPL_NS}section"):
        yield from _label_sections(child, label)


def parse_dailymed(entry: SourceEntry, data: bytes) -> list[SourcePassage]:
    root = ET.fromstring(data)
    set_id = root.find(SPL_NS + "setId")
    version = root.find(SPL_NS + "versionNumber")
    effective = root.find(SPL_NS + "effectiveTime")
    if (set_id is None or set_id.get("root") != entry.document_id.removeprefix("SPL-")
            or version is None or version.get("value") != entry.document_version
            or effective is None or effective.get("value") != entry.document_date.replace("-", "")):
        raise ValueError("DailyMed SPL identity, version, or effective date differs from manifest")
    passages = []
    for top in root.iter(SPL_NS + "section"):
        title_element = top.find(SPL_NS + "title")
        title = _clean("".join(title_element.itertext())) if title_element is not None else ""
        if title not in entry.sections:
            continue
        found = list(_label_sections(top))
        if not found:
            raise ValueError(f"Empty DailyMed label section {title}")
        for subsection, content in found:
            # Split large subsections at sentence boundaries while retaining exact offsets.
            starts = [0]
            for match in re.finditer(r"(?<=[.!?])\s+", content):
                if match.end() - starts[-1] >= 1200:
                    starts.append(match.end())
            starts.append(len(content))
            for start, end in zip(starts, starts[1:]):
                text = content[start:end].strip()
                if text:
                    passages.append(_passage(entry, f"{title} / {subsection}", text, start, str(entry.url)))
    if not passages:
        raise ValueError("No selected DailyMed label sections found")
    return passages


def build_passages(manifest: SourceManifest) -> dict[str, list[tuple[SourcePassage, str]]]:
    output = {kind: [] for kind in COLLECTIONS}
    for entry in manifest.sources:
        if entry.retired:
            continue
        data = checked_bytes(entry)
        parser = parse_nice if entry.format == "nice_recommendations_html" else parse_dailymed
        output[entry.source_type].extend((passage, entry.sha256) for passage in parser(entry, data))
    return output


def index_sources(manifest: SourceManifest, client, embedder) -> dict[str, int]:
    """Validate all snapshots, then replace only this manifest's dedicated collections."""
    grouped = build_passages(manifest)
    counts = {}
    for source_type, items in grouped.items():
        if not items:
            continue
        vectors = embedder.encode([p.passage for p, _ in items])
        vectors = [v.tolist() if hasattr(v, "tolist") else list(v) for v in vectors]
        if len(vectors) != len(items) or not vectors or not vectors[0]:
            raise ValueError("Embedding output does not match source passages")
        collection = COLLECTIONS[source_type]
        if client.collection_exists(collection):
            client.delete_collection(collection)
        client.create_collection(collection, vectors_config=VectorParams(size=len(vectors[0]), distance=Distance.COSINE))
        points = [PointStruct(id=str(uuid.uuid5(uuid.NAMESPACE_URL, passage.id)), vector=vector,
                              payload={"source_passage": passage.model_dump(mode="json"), "source_sha256": sha})
                  for (passage, sha), vector in zip(items, vectors)]
        client.upsert(collection_name=collection, points=points, wait=True)
        counts[collection] = len(points)
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["verify", "fetch", "ingest"])
    args = parser.parse_args()
    manifest = load_manifest()
    if args.action == "fetch":
        fetch_sources(manifest)
    elif args.action == "verify":
        counts = {kind: len(items) for kind, items in build_passages(manifest).items()}
        print(counts)
    else:
        from qdrant_client import QdrantClient
        from sentence_transformers import SentenceTransformer
        client = QdrantClient(settings.QDRANT_URL)
        embedder = SentenceTransformer("pritamdeka/S-PubMedBert-MS-MARCO")
        print(index_sources(manifest, client, embedder))


if __name__ == "__main__":
    main()
