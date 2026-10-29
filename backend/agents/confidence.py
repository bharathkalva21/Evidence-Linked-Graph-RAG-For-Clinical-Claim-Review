from typing import List, Dict, Any, Tuple
from backend.schemas.report import DiagnosisCandidate

class ConfidenceEvaluator:
    def evaluate(
        self, 
        diagnoses: List[DiagnosisCandidate], 
        conflicts: List[Dict[str, Any]], 
        missing_info: List[str]
    ) -> Tuple[float, str]:
        """
        Calculates overall confidence and decides the next action (report or retry).
        Returns (confidence_score, action_string)
        """
        if not diagnoses:
            return 0.0, "retry"
            
        # Base confidence is the confidence of the top diagnosis
        top_diagnosis = diagnoses[0]
        base_confidence = top_diagnosis.confidence
        
        # Penalize for severe conflicts
        severe_conflicts = len([c for c in conflicts if c.get("severity") == "high"])
        confidence = base_confidence - (severe_conflicts * 0.15)
        
        # Penalize for missing info
        confidence -= (len(missing_info) * 0.05)
        
        confidence = max(0.0, min(1.0, confidence))
        
        if confidence >= 0.65:
            return round(confidence, 2), "report"
        elif 0.45 <= confidence < 0.65:
            return round(confidence, 2), "report_with_limitations"
        else:
            return round(confidence, 2), "retry"
