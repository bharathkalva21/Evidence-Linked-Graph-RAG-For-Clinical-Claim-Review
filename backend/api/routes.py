from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Dict, Any

from backend.schemas.patient import PatientContext
from backend.schemas.report import ClinicalReport, DiagnosisCandidate
from backend.schemas.evidence import EvidenceItem

# We will inject services in the future, for now we instantiate or mock them in the route or main

router = APIRouter()

class AnalyzeRequest(BaseModel):
    case_text: str

@router.get("/health")
def health_check():
    return {"status": "ok", "service": "CDSS Backend"}

import os
from backend.services.ontology_parser import OntologyParser
from backend.services.entity_linker import EntityLinker
from backend.agents.clarifier import ClinicalClarifier
from backend.services.graph_retriever import GraphRetriever
from backend.services.vector_retriever import VectorRetriever
from backend.services.drugcentral import DrugCentralService
from backend.services.evidence_scanner import EvidenceScannerAgent
from backend.services.orchestrator import RetrievalOrchestrator
from backend.agents.evidence_ranker import EvidenceRanker
from backend.agents.conflict_detector import ConflictDetector
from backend.agents.fusion import ClinicalFusion
from backend.agents.confidence import ConfidenceEvaluator
from backend.agents.adaptive_retry import AdaptiveRetry
from backend.agents.report import ReportGenerator
from backend.services.claim_verifier import ClaimVerifier

# Global state for lazy initialization
pipeline_state = {}

def get_pipeline():
    if not pipeline_state:
        print("Initializing CDSS Pipeline Services...")
        
        # Paths
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        hpo_path = os.path.join(base_dir, "datasets", "ontologies", "hpo", "hp.obo")
        mondo_path = os.path.join(base_dir, "datasets", "ontologies", "mondo", "mondo.obo")
        kg_path = os.path.join(base_dir, "datasets", "kg.csv")
        drugcentral_dir = os.path.join(base_dir, "datasets", "drugcentral")
        drug_csv_path = os.path.join(drugcentral_dir, "structures.smiles.tsv")
        
        # 1. Init Ontologies & Linker
        parser = OntologyParser(hpo_path, mondo_path, drug_csv_path)
        parser.parse_all()
        linker = EntityLinker(parser.lookup_table)
        
        # 2. Init Retrievers
        graph_retriever = GraphRetriever(kg_path)
        vector_retriever = VectorRetriever() # We assume it's unpopulated for now unless build_index is called
        drug_service = DrugCentralService(drugcentral_dir)
        evidence_scanner = EvidenceScannerAgent()
        
        pipeline_state['clarifier'] = ClinicalClarifier(linker)
        pipeline_state['orchestrator'] = RetrievalOrchestrator(graph_retriever, vector_retriever, drug_service, evidence_scanner)
        pipeline_state['ranker'] = EvidenceRanker()
        pipeline_state['detector'] = ConflictDetector()
        pipeline_state['fusion'] = ClinicalFusion()
        pipeline_state['verifier'] = ClaimVerifier()
        pipeline_state['confidence'] = ConfidenceEvaluator()
        pipeline_state['retry'] = AdaptiveRetry(max_retries=2)
        pipeline_state['report'] = ReportGenerator()
        
        print("Pipeline initialization complete.")
    
    return pipeline_state

@router.post("/analyze")
def analyze_case(request: AnalyzeRequest):
    services = get_pipeline()
    
    clarifier = services['clarifier']
    orchestrator = services['orchestrator']
    ranker = services['ranker']
    detector = services['detector']
    fusion = services['fusion']
    verifier = services.get('verifier') or ClaimVerifier()
    confidence_evaluator = services['confidence']
    retry_agent = services['retry']
    report_generator = services['report']
    
    # 1. Clarify
    context = clarifier.process(request.case_text)
    
    attempt = 0
    action = "retry"
    
    while action == "retry" and attempt <= retry_agent.max_retries:
        print(f"--- Analysis Attempt {attempt + 1} ---")
        
        # 2. Retrieve
        retrieval_results = orchestrator.retrieve(context)
        
        # 3. Rank Evidence
        ranked_evidence = ranker.rank(context, retrieval_results)
        
        # 4. Detect Conflicts
        conflicts = detector.detect(context, retrieval_results, ranked_evidence)
        
        # 5. Clinical Fusion
        fusion_result = fusion.fuse(context, retrieval_results, ranked_evidence, conflicts)
        diagnoses = fusion_result.diagnoses
        missing_info = list(dict.fromkeys(context.missing_information + fusion_result.missing_information))

        # 6. Independently verify citations and apply label-backed safety rules.
        verification = verifier.verify(context, fusion_result.claims, retrieval_results.source_passages)
        safety_conflicts, safety_claims = detector.detect_medication_safety(
            context, verification.trusted_passages, verification.claims
        ) if hasattr(detector, 'detect_medication_safety') else ([], [])
        conflicts.extend(safety_conflicts)
        verification.claims.extend(safety_claims)
        verification.evidence_completeness['supported_claims'] = sum(
            claim.status == 'supported' for claim in verification.claims
        )
        verification.evidence_completeness['conflicting_claims'] = sum(
            claim.status == 'conflicting' for claim in verification.claims
        )
        verification.evidence_completeness['unverified_claims'] = sum(
            claim.status == 'unverified' for claim in verification.claims
        )
        verification.evidence_completeness['claim_count'] = len(verification.claims)
        if safety_conflicts:
            missing_info = list(dict.fromkeys(missing_info + [
                item['description'] for item in safety_conflicts
                if item['verification_status'] == 'unverified'
            ]))
        
        # 7. Preserve the legacy retry heuristic; this is not a probability.
        conf_score, action = confidence_evaluator.evaluate(diagnoses, conflicts, missing_info)
        
        if retry_agent.should_retry(attempt, action):
            print("Confidence too low, executing adaptive retry...")
            feedback = retry_agent.generate_feedback(context, conflicts)
            print(f"Optimizer Feedback: {feedback}")
            
            context = retry_agent.expand_context(context)
            
            # Keep extracted patient facts anchored to the original case, not generated feedback.
            expanded_query = context.expanded_query
            context = clarifier.process(request.case_text)
            context.expanded_query = f"{expanded_query}\n\n{feedback}"
            
            attempt += 1
        else:
            break
            
    # 8. Generate Report
    final_report = report_generator.generate(
        context=context,
        diagnoses=diagnoses,
        evidence=ranked_evidence,
        conflicts=conflicts,
        missing_info=missing_info,
        confidence=conf_score,
        limitations=["Local offline MVP execution. Not for clinical use.",
                     "Legacy confidence values are uncalibrated retry heuristics, not diagnostic probabilities."] + [
            f"Source retrieval unverified: {reason}"
            for reason in retrieval_results.source_retrieval_limitations
        ] + verification.failures,
        claims=verification.claims,
        source_passages=retrieval_results.source_passages,
        evidence_completeness=verification.evidence_completeness,
        verification_failures=verification.failures,
    )
    
    return {
        "patient_context": context.model_dump(),
        "retrieval": {
            "graph_candidates": len(retrieval_results.graph_results.candidate_diseases),
            "vector_items": len(retrieval_results.vector_results.evidence_items),
            "drug_safety_matches": len(retrieval_results.drug_safety_results),
            "authoritative_passages": len(retrieval_results.source_passages),
        },
        "report": final_report.model_dump()
    }
