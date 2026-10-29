from rapidfuzz import process, fuzz
from typing import List, Dict, Any, Tuple
import re

from backend.schemas.patient import LinkedEntity

class EntityLinker:
    def __init__(self, lookup_table: Dict[str, List[Dict[str, str]]]):
        """
        Initializes the linker with the pre-built lookup table from the ontology parser.
        lookup_table: mapping of normalized text -> list of dicts {"id", "source", "name"}
        """
        self.lookup_table = lookup_table
        self.vocab = list(self.lookup_table.keys())

    def _normalize_string(self, s: str) -> str:
        s = s.lower()
        s = re.sub(r'[^\w\s]', '', s)
        s = re.sub(r'\s+', ' ', s).strip()
        return s

    def link(self, raw_text: str, entity_type: str, threshold: float = 85.0) -> LinkedEntity:
        """
        Links raw text to an ontology concept using exact match, then fuzzy match.
        """
        norm_text = self._normalize_string(raw_text)
        
        # 1. Exact Match
        if norm_text in self.lookup_table:
            candidates = self.lookup_table[norm_text]
            best_candidate = candidates[0] # Pick the first match
            return LinkedEntity(
                text=raw_text,
                normalized_name=best_candidate["name"],
                entity_type=entity_type,
                ontology_id=best_candidate["id"],
                ontology_source=best_candidate["source"],
                confidence=1.0,
                candidates=candidates
            )
        
        # 2. Fuzzy Match
        if not self.vocab:
            return LinkedEntity(text=raw_text, entity_type=entity_type)
            
        results = process.extract(
            norm_text, 
            self.vocab, 
            scorer=fuzz.WRatio, 
            limit=5
        )
        
        if results:
            best_match, score, _ = results[0]
            if score >= threshold:
                candidates = self.lookup_table[best_match]
                best_candidate = candidates[0]
                
                return LinkedEntity(
                    text=raw_text,
                    normalized_name=best_candidate["name"],
                    entity_type=entity_type,
                    ontology_id=best_candidate["id"],
                    ontology_source=best_candidate["source"],
                    confidence=score / 100.0,
                    candidates=candidates
                )
        
        # 3. No match found
        return LinkedEntity(text=raw_text, entity_type=entity_type)
