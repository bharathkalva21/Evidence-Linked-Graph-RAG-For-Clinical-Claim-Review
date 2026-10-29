from pydantic import BaseModel, Field
from typing import List, Dict, Any
from .evidence import SourcePassage

class GraphPath(BaseModel):
    nodes: List[Dict[str, Any]]
    relationships: List[str]
    score: float = 0.0

class GraphRetrievalResult(BaseModel):
    candidate_diseases: List[Dict[str, Any]]
    paths: List[GraphPath]
    contraindications: List[Dict[str, Any]] = []
    drug_interactions: List[Dict[str, Any]] = []
    limitations: List[str] = []

class VectorRetrievalResult(BaseModel):
    evidence_items: List[Dict[str, Any]] = []

class OrchestratorResult(BaseModel):
    graph_results: GraphRetrievalResult
    vector_results: VectorRetrievalResult
    drug_safety_results: List[Dict[str, Any]] = []
    web_search_results: List[Dict[str, Any]] = []
    source_passages: List[SourcePassage] = Field(default_factory=list)
    source_retrieval_limitations: List[str] = Field(default_factory=list)
