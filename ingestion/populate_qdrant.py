import os
import sys
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from sentence_transformers import SentenceTransformer

def chunk_text(text: str, chunk_size: int = 150, overlap: int = 20) -> list[str]:
    words = text.split()
    chunks = []
    for i in range(0, len(words), chunk_size - overlap):
        chunk = " ".join(words[i:i + chunk_size])
        if chunk:
            chunks.append(chunk)
    return chunks

def populate():
    print("Initializing Qdrant Client...")
    client = QdrantClient("http://localhost:6333")
    collection_name = "medical_textbooks"
    
    try:
        client.get_collection(collection_name)
        print(f"Collection {collection_name} already exists. Recreating...")
        client.delete_collection(collection_name)
    except Exception:
        pass

    client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=768, distance=Distance.COSINE),
    )

    print("Loading SentenceTransformer model (pritamdeka/S-PubMedBert-MS-MARCO)...")
    model = SentenceTransformer('pritamdeka/S-PubMedBert-MS-MARCO')

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    file_path = os.path.join(base_dir, "datasets", "literature", "MedQA", "MedQA-USMLE", "textbooks", "en", "First_Aid_Step1.txt")
    
    print(f"Reading {file_path}...")
    with open(file_path, 'r', encoding='utf-8') as f:
        text = f.read()

    print("Chunking text (first 150k chars for test)...")
    text = text[:150000]
    chunks = chunk_text(text, chunk_size=150, overlap=20)
    print(f"Created {len(chunks)} chunks.")

    print("Encoding chunks to vectors...")
    embeddings = model.encode(chunks, show_progress_bar=True)

    print("Uploading to Qdrant...")
    points = [
        PointStruct(
            id=i,
            vector=embedding.tolist(),
            payload={"text": chunk, "source": "First_Aid_Step1"}
        )
        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings))
    ]
    
    client.upsert(
        collection_name=collection_name,
        points=points
    )
    print("Ingestion complete!")

if __name__ == "__main__":
    populate()
