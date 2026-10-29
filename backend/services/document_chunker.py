import os
import glob
from typing import List, Dict, Any

class DocumentChunker:
    def __init__(self, chunk_size: int = 500, overlap: int = 100):
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk_text(self, text: str, metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
        words = text.split()
        chunks = []
        
        if not words:
            return chunks

        step = self.chunk_size - self.overlap
        if step <= 0:
            step = self.chunk_size # Fallback if overlap is too large

        for i in range(0, len(words), step):
            chunk_words = words[i:i + self.chunk_size]
            chunk_text = " ".join(chunk_words)
            
            chunk_meta = metadata.copy()
            chunk_meta["chunk_index"] = len(chunks)
            
            chunks.append({
                "text": chunk_text,
                "metadata": chunk_meta
            })
            
            if i + self.chunk_size >= len(words):
                break
                
        return chunks

    def process_directory(self, dir_path: str, glob_pattern: str = "*.txt") -> List[Dict[str, Any]]:
        all_chunks = []
        search_path = os.path.join(dir_path, glob_pattern)
        
        for file_path in glob.glob(search_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    text = f.read()
                
                metadata = {
                    "source_file": os.path.basename(file_path),
                    "source_path": file_path
                }
                
                chunks = self.chunk_text(text, metadata)
                all_chunks.extend(chunks)
            except Exception as e:
                print(f"Error processing file {file_path}: {e}")
                
        return all_chunks
