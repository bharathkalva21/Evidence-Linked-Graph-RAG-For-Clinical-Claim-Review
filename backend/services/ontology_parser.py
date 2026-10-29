import re
from typing import Dict, List, Any

class OntologyParser:
    def __init__(self, hpo_path: str, mondo_path: str, drug_csv_path: str = None):
        self.hpo_path = hpo_path
        self.mondo_path = mondo_path
        self.drug_csv_path = drug_csv_path
        self.hpo_terms: Dict[str, Any] = {}
        self.mondo_terms: Dict[str, Any] = {}
        self.drug_terms: Dict[str, Any] = {}
        self.lookup_table: Dict[str, List[Dict[str, str]]] = {}

    def _normalize_string(self, s: str) -> str:
        s = s.lower()
        s = re.sub(r'[^\w\s]', '', s)
        s = re.sub(r'\s+', ' ', s).strip()
        return s

    def _parse_obo(self, file_path: str) -> Dict[str, Any]:
        terms = {}
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        except FileNotFoundError:
            print(f"File not found: {file_path}")
            return terms

        current_term = None
        in_term_block = False

        for line in lines:
            line = line.strip()
            if line == "[Term]":
                in_term_block = True
                if current_term and current_term.get("id"):
                    terms[current_term["id"]] = current_term
                current_term = {"synonyms": [], "is_obsolete": False}
                continue
            
            if not in_term_block or not line:
                continue
            
            if ":" not in line:
                continue
            
            key, val = line.split(":", 1)
            val = val.strip()

            if key == "id":
                current_term["id"] = val
            elif key == "name":
                current_term["name"] = val
            elif key == "def":
                current_term["def"] = val
            elif key == "synonym":
                # Extract synonym string from quotes
                match = re.search(r'"([^"]*)"', val)
                if match:
                    current_term["synonyms"].append(match.group(1))
            elif key == "is_obsolete" and val == "true":
                current_term["is_obsolete"] = True

        if current_term and current_term.get("id"):
            terms[current_term["id"]] = current_term

        # Filter out obsolete
        terms = {k: v for k, v in terms.items() if not v.get("is_obsolete")}
        return terms

    def _build_lookup(self, terms: Dict[str, Any], source: str):
        for term_id, term_data in terms.items():
            name = term_data.get("name", "")
            if name:
                norm_name = self._normalize_string(name)
                if norm_name:
                    if norm_name not in self.lookup_table:
                        self.lookup_table[norm_name] = []
                    self.lookup_table[norm_name].append({
                        "id": term_id,
                        "source": source,
                        "name": name
                    })

            for syn in term_data.get("synonyms", []):
                norm_syn = self._normalize_string(syn)
                if norm_syn:
                    if norm_syn not in self.lookup_table:
                        self.lookup_table[norm_syn] = []
                    self.lookup_table[norm_syn].append({
                        "id": term_id,
                        "source": source,
                        "name": name
                    })

    def _parse_drug_tsv(self, file_path: str) -> Dict[str, Any]:
        terms = {}
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        except FileNotFoundError:
            print(f"File not found: {file_path}")
            return terms
            
        for line in lines[1:]: # Skip header
            parts = line.strip().split('\t')
            if len(parts) >= 5:
                drug_id = parts[3]
                drug_name = parts[4].strip()
                if drug_name:
                    terms[drug_id] = {
                        "id": drug_id,
                        "name": drug_name,
                        "synonyms": []
                    }
        return terms

    def parse_all(self):
        print(f"Parsing HPO from {self.hpo_path}...")
        self.hpo_terms = self._parse_obo(self.hpo_path)
        print(f"Parsing MONDO from {self.mondo_path}...")
        self.mondo_terms = self._parse_obo(self.mondo_path)
        
        self._build_lookup(self.hpo_terms, "HPO")
        self._build_lookup(self.mondo_terms, "MONDO")
        
        if self.drug_csv_path:
            print(f"Parsing Drugs from {self.drug_csv_path}...")
            self.drug_terms = self._parse_drug_tsv(self.drug_csv_path)
            self._build_lookup(self.drug_terms, "DRUG")
            
        print(f"Built lookup table with {len(self.lookup_table)} unique normalized names/synonyms.")
