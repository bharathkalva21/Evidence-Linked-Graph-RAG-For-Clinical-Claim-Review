from backend.schemas.patient import PatientContext, LinkedEntity

class AdaptiveRetry:
    def __init__(self, max_retries: int = 3):
        self.max_retries = max_retries
        
    def should_retry(self, current_attempt: int, action: str) -> bool:
        """
        Determines if a retry should be executed based on the action and max retries.
        """
        return action == "retry" and current_attempt < self.max_retries
        
    def generate_feedback(self, context: PatientContext, conflicts: list) -> str:
        """
        Generates improvement suggestions and optimized queries for the Clarifier Agent.
        """
        feedback = f"Attempt failed due to low confidence. Please re-evaluate the clinical text: '{context.raw_input}'."
        if conflicts:
            feedback += f" Consider resolving these conflicts: {[c.get('description', '') for c in conflicts]}."
        return feedback
        
    def expand_context(self, context: PatientContext) -> PatientContext:
        """
        Expands the patient context for the next retry attempt.
        For MVP, we append known candidates' synonyms to the expanded_query.
        """
        if not context.expanded_query:
            context.expanded_query = context.raw_input
            
        expanded_input = context.expanded_query
        
        # Add synonyms for symptoms to the query to broaden vector retrieval
        for sym in context.symptoms:
            if sym.candidates:
                # Add up to 2 synonyms
                synonyms = []
                # Simple extraction, assuming candidates have 'name' or 'synonyms'
                for cand in sym.candidates[:2]:
                    if "name" in cand and cand["name"].lower() not in expanded_input.lower():
                        synonyms.append(cand["name"])
                
                if synonyms:
                    expanded_input += f" {', '.join(synonyms)}"
                    
        context.expanded_query = expanded_input
        return context
