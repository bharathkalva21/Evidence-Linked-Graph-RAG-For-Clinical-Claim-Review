from typing import List, Dict, Any
from backend.schemas.patient import PatientContext
from backend.schemas.retrieval import OrchestratorResult, VectorRetrievalResult, GraphRetrievalResult
from backend.services.graph_retriever import GraphRetriever
from backend.services.vector_retriever import VectorRetriever
from backend.services.drugcentral import DrugCentralService
from backend.services.evidence_scanner import EvidenceScannerAgent

class RetrievalOrchestrator:
    def __init__(
        self, 
        graph_retriever: GraphRetriever, 
        vector_retriever: VectorRetriever,
        drugcentral_service: DrugCentralService,
        evidence_scanner: EvidenceScannerAgent
    ):
        self.graph_retriever = graph_retriever
        self.vector_retriever = vector_retriever
        self.drugcentral_service = drugcentral_service
        self.evidence_scanner = evidence_scanner

    def retrieve(self, context: PatientContext) -> OrchestratorResult:
        """
        Executes fan-out retrieval across Graph, Vector, Drug safety, and Web sources independently.
        """
        print("Orchestrator: Initiating Graph Retrieval...")
        graph_results = self.graph_retriever.retrieve(context)
        
        print("Orchestrator: Initiating Vector Retrieval...")
        vector_items = self.vector_retriever.retrieve(context)
        vector_results = VectorRetrievalResult(evidence_items=vector_items)
        source_passages, source_limitations = self.vector_retriever.retrieve_authoritative(context)
        
        print("Orchestrator: Initiating Drug Safety Retrieval...")
        drug_safety_results = []
        for med in context.medications:
            drug_name = med.normalized_name or med.text
            if drug_name:
                targets = self.drugcentral_service.get_drug_targets(drug_name)
                if targets:
                    drug_safety_results.append({
                        "drug": drug_name,
                        "targets": targets
                    })
                    
        print("Orchestrator: Initiating Web Scanner Retrieval...")
        web_search_results = self.evidence_scanner.search(context)
                    
        return OrchestratorResult(
            graph_results=graph_results,
            vector_results=vector_results,
            drug_safety_results=drug_safety_results,
            web_search_results=web_search_results,
            source_passages=source_passages,
            source_retrieval_limitations=source_limitations,
        )
