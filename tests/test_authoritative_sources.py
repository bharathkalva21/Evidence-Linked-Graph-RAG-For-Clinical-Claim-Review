"""Source ingestion must only admit complete passages from pinned documents."""

import hashlib
import uuid

import pytest
from pydantic import ValidationError
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct

from backend.schemas.evidence import SourcePassage
from backend.services.vector_retriever import VectorRetriever
from ingestion import authoritative_sources as sources


class KeywordEmbedder:
    def encode(self, text):
        def vector(value):
            value = value.lower()
            return [1.0 if "calcium-channel" in value else 0.01,
                    1.0 if "hypersensitivity" in value else 0.01,
                    0.01]
        return [vector(item) for item in text] if isinstance(text, list) else vector(text)


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "PROJECT_ROOT", tmp_path)
    source_dir = tmp_path / "datasets/authoritative"
    source_dir.mkdir(parents=True)
    nice = b'<article id="ng136-1_4_35"><div class="recommendation__body">Offer a calcium-channel blocker for eligible adults.</div></article>'
    label = b'''<document xmlns="urn:hl7-org:v3"><effectiveTime value="20260101"/><setId root="abc"/><versionNumber value="2"/>
    <component><section><title>4 CONTRAINDICATIONS</title><component><section><title>4.1 Hypersensitivity</title><text>Amlodipine is contraindicated in patients with hypersensitivity.</text></section></component></section></component></document>'''
    (source_dir / "nice.html").write_bytes(nice)
    (source_dir / "label.xml").write_bytes(label)
    common = {"jurisdiction": "Example jurisdiction", "reuse_terms": "Local fixture", "clinical_scope": "Adult hypertension", "retired": False}
    manifest = sources.SourceManifest.model_validate({
        "clinical_area": "Adult hypertension", "manifest_version": "1", "review_status": "Fixture",
        "sources": [
            {**common, "source_type": "guideline", "source_name": "NICE", "publisher": "NICE",
             "document_id": "NG136", "document_version": "2026-02-26", "title": "Hypertension",
             "document_date": "2019-08-28", "updated_date": "2026-02-26",
             "url": "https://www.nice.org.uk/guidance/ng136/chapter/Recommendations",
             "local_path": "datasets/authoritative/nice.html", "sha256": hashlib.sha256(nice).hexdigest(),
             "format": "nice_recommendations_html", "sections": ["1.4.35"]},
            {**common, "source_type": "drug_label", "source_name": "DailyMed", "publisher": "Example labeler",
             "document_id": "SPL-abc", "document_version": "2", "title": "Amlodipine label",
             "document_date": "2026-01-01", "updated_date": "2026-01-01",
             "url": "https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=abc",
             "local_path": "datasets/authoritative/label.xml", "sha256": hashlib.sha256(label).hexdigest(),
             "format": "dailymed_spl_xml", "sections": ["4 CONTRAINDICATIONS"]},
        ],
    })
    monkeypatch.setattr(sources, "load_manifest", lambda: manifest)
    return manifest, source_dir


def test_repeatable_index_and_exact_section_retrieval(corpus):
    manifest, _ = corpus
    client = QdrantClient(":memory:")
    embedder = KeywordEmbedder()
    first = sources.index_sources(manifest, client, embedder)
    assert first == {sources.COLLECTIONS["guideline"]: 1, sources.COLLECTIONS["drug_label"]: 1}
    assert sources.index_sources(manifest, client, embedder) == first

    retriever = VectorRetriever.__new__(VectorRetriever)
    retriever.client, retriever.model, retriever.is_ready = client, embedder, True
    passages, limitations = retriever.retrieve_authoritative_query("calcium-channel blocker", top_k=1)
    assert not limitations
    assert any(p.section == "Recommendation 1.4.35" and "calcium-channel blocker" in p.passage for p in passages)
    assert all(p.id.startswith("src_") and p.publisher and p.url for p in passages)


def test_rejects_changed_snapshot_and_forged_citation(corpus):
    manifest, source_dir = corpus
    client = QdrantClient(":memory:")
    embedder = KeywordEmbedder()
    sources.index_sources(manifest, client, embedder)
    retriever = VectorRetriever.__new__(VectorRetriever)
    retriever.client, retriever.model, retriever.is_ready = client, embedder, True

    # Search snippets and incomplete metadata cannot be promoted to a source passage.
    client.upsert(collection_name=sources.COLLECTIONS["guideline"], points=[PointStruct(
        id=str(uuid.uuid4()), vector=[1.0, 0.01, 0.01],
        payload={"source_passage": {"source_type": "guideline", "passage": "Search snippet"},
                 "source_sha256": manifest.sources[0].sha256},
    )])
    original = sources.build_passages(manifest)["guideline"][0][0]
    forged_fields = original.model_dump(mode="json") | {
        "id": "", "passage": "A fabricated calcium-channel recommendation.",
        "span_end": len("A fabricated calcium-channel recommendation."),
    }
    forged = SourcePassage.model_validate(forged_fields)
    client.upsert(collection_name=sources.COLLECTIONS["guideline"], points=[PointStruct(
        id=str(uuid.uuid4()), vector=[1.0, 0.01, 0.01],
        payload={"source_passage": forged.model_dump(mode="json"),
                 "source_sha256": manifest.sources[0].sha256},
    )])
    passages, limitations = retriever.retrieve_authoritative_query("calcium-channel blocker", top_k=10)
    assert len(passages) == 2
    assert sum("Rejected invalid guideline citation payload" in reason for reason in limitations) == 2

    (source_dir / "nice.html").write_bytes(b"changed without version review")
    passages, limitations = retriever.retrieve_authoritative_query("calcium-channel blocker")
    assert not passages
    assert any("checksum mismatch" in reason for reason in limitations)


def test_manifest_rejects_snippet_host_and_missing_provenance(corpus):
    manifest, _ = corpus
    entry = manifest.sources[0].model_dump(mode="json")
    with pytest.raises(ValidationError, match="approved official host"):
        sources.SourceEntry.model_validate({**entry, "url": "https://search.example/snippet"})
    with pytest.raises(ValidationError):
        sources.SourceEntry.model_validate({**entry, "publisher": ""})
