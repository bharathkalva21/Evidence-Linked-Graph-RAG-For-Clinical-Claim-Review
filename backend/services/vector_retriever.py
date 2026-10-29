from typing import List, Dict, Any
from backend.schemas.patient import PatientContext
from backend.config import settings
from backend.schemas.evidence import SourcePassage

class VectorRetriever:
    def __init__(self):
        try:
            from qdrant_client import QdrantClient
            from sentence_transformers import SentenceTransformer
            self.client = QdrantClient(settings.QDRANT_URL)
            self.model = SentenceTransformer('pritamdeka/S-PubMedBert-MS-MARCO')
            self.collection_name = settings.VECTOR_COLLECTION_TEXTBOOKS
            self.is_ready = True
        except Exception as e:
            print(f"Failed to initialize VectorRetriever: {e}")
            self.is_ready = False

    def build_index(self, chunks: List[Dict[str, Any]]):
        """No-op. Indexing is now handled out-of-band by ingestion scripts into Qdrant."""
        pass

    def retrieve(self, context: PatientContext, top_k: int = 5) -> List[Dict[str, Any]]:
        if not self.is_ready:
            return []

        base_query = context.expanded_query if context.expanded_query else context.raw_input
        query_parts = [base_query]
        query_parts.extend([s.text for s in context.symptoms])
        query = " ".join(query_parts)

        try:
            query_vec = self.model.encode(query).tolist()
            search_result = self.client.query_points(
                collection_name=self.collection_name, query=query_vec, limit=top_k
            )
            results = []
            for hit in search_result.points:
                if hit.score > 0.4:
                    results.append({
                        "text": hit.payload.get("text", ""),
                        "metadata": {"source": hit.payload.get("source", "")},
                        "score": hit.score,
                    })
            return results
        except Exception as e:
            print(f"Vector search failed: {e}")
            return []

    def retrieve_authoritative(self, context: PatientContext, top_k: int = 5) -> tuple[list[SourcePassage], list[str]]:
        query = context.expanded_query or context.raw_input
        return self.retrieve_authoritative_query(query, top_k)

    def retrieve_authoritative_query(self, query: str, top_k: int = 5) -> tuple[list[SourcePassage], list[str]]:
        """Return only pinned, checksum-verified source passages; report every unavailable collection."""
        from ingestion.authoritative_sources import COLLECTIONS, build_passages, load_manifest

        if not self.is_ready:
            return [], ["Authoritative vector retrieval is unavailable"]
        try:
            manifest = load_manifest()
            active = {entry.document_id: entry for entry in manifest.sources if not entry.retired}
            verified_ids = {p.id for items in build_passages(manifest).values() for p, _ in items}
        except Exception as exc:
            return [], [f"Authoritative source manifest or snapshot unavailable: {exc}"]

        passages: list[SourcePassage] = []
        limitations: list[str] = []
        try:
            vector = self.model.encode(query)
            vector = vector.tolist() if hasattr(vector, "tolist") else list(vector)
        except Exception as exc:
            return [], [f"Authoritative query embedding unavailable: {exc}"]
        for kind, collection in COLLECTIONS.items():
            if not any(entry.source_type == kind for entry in active.values()):
                continue
            try:
                hits = self.client.query_points(collection_name=collection, query=vector,
                                                limit=top_k, with_payload=True).points
            except Exception as exc:
                limitations.append(f"{kind} collection unavailable: {exc}")
                continue
            if not hits:
                limitations.append(f"{kind} collection has no matching source passages")
            for hit in hits:
                try:
                    payload = hit.payload or {}
                    passage = SourcePassage.model_validate(payload["source_passage"])
                    entry = active[passage.document_id]
                    if (entry.source_type != kind or passage.document_version != entry.document_version
                            or payload.get("source_sha256") != entry.sha256
                            or passage.id not in verified_ids):
                        raise ValueError("source version or checksum does not match manifest")
                    passages.append(passage)
                except (KeyError, ValueError, TypeError) as exc:
                    limitations.append(f"Rejected invalid {kind} citation payload: {exc}")
        return passages, limitations
