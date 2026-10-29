import re

from backend.schemas.patient import PatientContext, LinkedEntity
from backend.services.entity_linker import EntityLinker
from backend.services.llm_fallback import LLMFallback
from backend.services.patient_fact_extractor import extract_safety_facts

class ClinicalClarifier:
    def __init__(self, entity_linker: EntityLinker):
        self.linker = entity_linker
        self.llm = LLMFallback()

    def process(self, raw_text: str) -> PatientContext:
        """
        Extracts patient context with Gemini, Cohere, Mistral, and OpenRouter fallbacks.
        """
        prompt = (
            "You are a medical data extraction system. Extract the clinical information from the following text into JSON.\n"
            "Output strictly valid JSON with the following structure. If a field is missing, use null or an empty list.\n\n"
            "{\n"
            '  "age": 45,\n'
            '  "sex": "male",\n'
            '  "safety_flags": ["chest pain", "shortness of breath"],\n'
            '  "symptoms": ["headache", "nausea"],\n'
            '  "conditions": ["type 2 diabetes", "hypertension"],\n'
            '  "medications": ["metformin", "lisinopril"],\n'
            '  "medication_statements": [{"name": "metformin", "status": "current", "source_phrase": "takes metformin"}],\n'
            '  "allergy_statements": [{"substance": "penicillin", "source_phrase": "allergic to penicillin"}]\n'
            "}\n\n"
            "Only extract facts stated in the clinical text. Copy source_phrase exactly; do not infer a normal finding from missing information.\n"
            f"Clinical Text:\n{raw_text}"
        )
        
        def validate_extraction(data):
            for field in ("symptoms", "conditions", "medications", "safety_flags"):
                if not isinstance(data.get(field, []), list):
                    raise ValueError(f"{field} must be a list")
                if any(not isinstance(item, str) for item in data.get(field, [])):
                    raise ValueError(f"{field} must contain strings")
            for field in ("medication_statements", "allergy_statements"):
                if not isinstance(data.get(field, []), list):
                    raise ValueError(f"{field} must be a list")

        parsed = self.llm.generate_json(
            prompt,
            "You are a clinical entity extractor. Output JSON only.",
            validate=validate_extraction,
        )

        # Hard fallback to prevent crashes if all 4 APIs go down or limits are exceeded
        if not parsed:
            print("WARNING: All Clarifier LLMs failed! Falling back to basic extraction.")
            parsed = {"age": None, "sex": None, "safety_flags": [], "symptoms": [], "conditions": [], "medications": []}
            
        # Parse extracted lists and link them
        facts = extract_safety_facts(raw_text, parsed)
        age_match = re.search(r"\b(\d{1,3})\s*[- ]year[- ]old\b|\baged?\s+(\d{1,3})\b", raw_text, re.I)
        age = int(next(group for group in age_match.groups() if group)) if age_match else None
        if age is not None and not 0 < age < 120:
            age = None
        sex_match = re.search(r"\b(male|female|man|woman)\b", raw_text, re.I)
        sex = {"man": "male", "woman": "female"}.get(sex_match.group(1).lower(), sex_match.group(1).lower()) if sex_match else None
        stated_flags = [flag for flag in parsed.get("safety_flags", []) if flag.casefold() in raw_text.casefold()]
        safety_flags = list(dict.fromkeys(stated_flags + facts["safety_flags"]))
        
        symptoms = []
        symptom_names = parsed.get("symptoms", []).copy()
        for critical_symptom in ("chest pain", "shortness of breath"):
            if re.search(rf"\b{re.escape(critical_symptom)}\b", raw_text, re.I):
                if critical_symptom not in (name.lower() for name in symptom_names):
                    symptom_names.append(critical_symptom)
                if critical_symptom not in safety_flags:
                    safety_flags.append(critical_symptom)
        for sym in symptom_names:
            linked = self.linker.link(sym, "symptom")
            symptoms.append(linked)
            
        conditions = []
        for cond in parsed.get("conditions", []):
            linked = self.linker.link(cond, "condition")
            conditions.append(linked)
            
        medications = []
        for statement in facts["current_medications"]:
            linked = self.linker.link(statement.name, "medication")
            if linked.ontology_source not in (None, "DRUG"):
                linked = LinkedEntity(text=statement.name, entity_type="medication")
            linked.source_phrase = statement.source_phrase
            linked.extraction_certainty = statement.extraction_certainty
            medications.append(linked)

        allergies = []
        for name, quote in facts["allergy_mentions"]:
            linked = self.linker.link(name, "allergy")
            if linked.ontology_source not in (None, "DRUG"):
                linked = LinkedEntity(text=name, entity_type="allergy")
            linked.source_phrase = quote
            linked.extraction_certainty = "explicit"
            allergies.append(linked)

        missing_information = facts["missing_information"].copy()
        if facts["hypertension_scope"] and age is None:
            missing_information.append("Age not supplied for hypertension treatment selection")

        return PatientContext(
            raw_input=raw_text,
            age=age,
            sex=sex,
            symptoms=symptoms,
            known_conditions=conditions,
            medications=medications,
            medication_statements=facts["medication_statements"],
            medication_list_status=facts["medication_list_status"],
            allergies=allergies,
            allergy_status=facts["allergy_status"],
            allergy_source_phrase=facts["allergy_source_phrase"],
            blood_pressure_readings=facts["blood_pressure_readings"],
            pregnancy_status=facts["pregnancy_status"],
            pregnancy_source_phrase=facts["pregnancy_source_phrase"],
            hypertension_confirmed=facts["hypertension_confirmed"],
            hypertension_source_phrase=facts["hypertension_source_phrase"],
            hypertension_scope=facts["hypertension_scope"],
            vitals={"blood_pressure_readings": [reading.model_dump() for reading in facts["blood_pressure_readings"]]}
                   if facts["blood_pressure_readings"] else {},
            labs=facts["labs"],
            missing_information=missing_information,
            safety_flags=safety_flags,
        )
