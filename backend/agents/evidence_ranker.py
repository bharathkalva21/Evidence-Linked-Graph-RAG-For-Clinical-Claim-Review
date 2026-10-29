import uuid
from typing import List
from backend.schemas.patient import PatientContext
from backend.schemas.retrieval import OrchestratorResult
from backend.schemas.evidence import EvidenceItem

class EvidenceRanker:
    def rank(self, context: PatientContext, retrieval_result: OrchestratorResult) -> List[EvidenceItem]:
        """
        Takes unmerged retrieval results and applies heuristic scoring based on specificity, 
        source reliability, and context overlap.
        """
        all_evidence: List[EvidenceItem] = []
        
        # 1. Process Graph Evidence
        for g_candidate in retrieval_result.graph_results.candidate_diseases:
            # Create a summary evidence item for each candidate disease
            disease_name = g_candidate.get("name", "Unknown")
            raw_score = g_candidate.get("score", 0.0)
            
            # Simple heuristic: heavily weight graph exact matches
            final_score = raw_score * 1.5
            
            ev = EvidenceItem(
                id=str(uuid.uuid4()),
                source_type="graph",
                source_name="Local KG",
                title=f"Graph Path to {disease_name}",
                text=f"The patient's symptoms strongly link to {disease_name} in the Knowledge Graph.",
                score=final_score,
                supports=[disease_name]
            )
            all_evidence.append(ev)
            
        # 2. Process Vector Evidence
        for v_item in retrieval_result.vector_results.evidence_items:
            raw_score = v_item.get("score", 0.0)
            text = v_item.get("text", "")
            
            # Heuristic: Give a slight boost if a known condition or symptom is explicitly in the text
            boost = 0.0
            lower_text = text.lower()
            for sym in context.symptoms:
                if sym.normalized_name and sym.normalized_name.lower() in lower_text:
                    boost += 0.1
            
            final_score = raw_score + boost
            
            ev = EvidenceItem(
                id=str(uuid.uuid4()),
                source_type="vector",
                source_name=v_item.get("metadata", {}).get("source", "Literature"),
                title=v_item.get("metadata", {}).get("title", "Literature Match"),
                text=text,
                score=final_score
            )
            all_evidence.append(ev)
            
        # 3. Process Drug Safety Evidence
        for safety_record in retrieval_result.drug_safety_results:
            drug = safety_record.get("drug")
            targets = safety_record.get("targets", [])
            
            if targets:
                target_names = [t.get('target_name') for t in targets if t.get('target_name')]
                ev = EvidenceItem(
                    id=str(uuid.uuid4()),
                    source_type="drugcentral",
                    source_name="DrugCentral API/Dump",
                    title=f"Drug Safety: {drug}",
                    text=f"{drug} has {len(targets)} known targets including: {', '.join(target_names[:3])}.",
                    score=1.0, # High reliability for raw safety data
                    metadata={"drug": drug, "target_count": len(targets)}
                )
                all_evidence.append(ev)

        # Sort by score descending
        all_evidence.sort(key=lambda x: x.score, reverse=True)
        return all_evidence
