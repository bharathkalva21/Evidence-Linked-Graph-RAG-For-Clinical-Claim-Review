"""Safety facts must remain explicit and traceable through extraction and retries."""

from backend.agents.clarifier import ClinicalClarifier
from backend.agents.fusion import ClinicalFusion, FusionResult
from backend.agents.report import ReportGenerator
from backend.api import routes
from backend.schemas.retrieval import GraphRetrievalResult, OrchestratorResult, VectorRetrievalResult
from backend.services.entity_linker import EntityLinker


def clarifier(parsed=None):
    instance = ClinicalClarifier(EntityLinker({}))
    instance.llm.generate_json = lambda *args, **kwargs: parsed or {
        "symptoms": [], "conditions": [], "medications": [], "safety_flags": [],
    }
    return instance


def test_explicit_allergy_current_medicine_and_observations():
    text = ("A 55-year-old woman with confirmed hypertension. Clinic BP 150/95 mmHg. "
            "Takes amlodipine. Allergic to penicillin. Not pregnant. Potassium 4.2 and eGFR 80.")
    context = clarifier().process(text)
    assert context.age == 55
    assert context.allergy_status == "allergies_reported"
    assert [(item.text, item.source_phrase, item.extraction_certainty) for item in context.allergies] == [
        ("penicillin", "Allergic to penicillin", "explicit")]
    assert context.medication_list_status == "reported"
    assert [(item.text, item.source_phrase) for item in context.medications] == [("amlodipine", "Takes amlodipine")]
    assert context.blood_pressure_readings[0].method == "clinic"
    assert context.blood_pressure_readings[0].systolic_mm_hg == 150
    assert {lab["name"] for lab in context.labs} == {"potassium", "egfr"}
    assert "Unit for potassium result not supplied" in context.missing_information
    assert context.pregnancy_status == "not_pregnant"
    assert context.hypertension_confirmed is True
    assert "Allergy status not supplied" not in context.missing_information


def test_medicine_and_allergen_do_not_inherit_non_drug_ontology_matches():
    linker = EntityLinker({"amlodipine": [{"id": "HP:fake", "source": "HPO", "name": "Wrong concept"}],
                           "penicillin": [{"id": "MONDO:fake", "source": "MONDO", "name": "Wrong disease"}]})
    extractor = ClinicalClarifier(linker)
    extractor.llm.generate_json = lambda *args, **kwargs: {
        "symptoms": [], "conditions": [], "medications": [], "safety_flags": []}
    context = extractor.process("Takes amlodipine. Allergic to penicillin.")
    assert context.medications[0].normalized_name is None
    assert context.medications[0].text == "amlodipine"
    assert context.allergies[0].normalized_name is None
    assert context.allergies[0].text == "penicillin"


def test_explicit_no_known_allergies_is_distinct_from_unknown():
    known_none = clarifier().process("No known drug allergies. Takes no medications.")
    assert known_none.allergy_status == "no_known_allergies"
    assert known_none.allergy_source_phrase == "No known drug allergies"
    assert known_none.allergies == []
    assert known_none.medication_list_status == "none_reported"

    unknown = clarifier().process("High blood pressure is being evaluated.")
    assert unknown.allergy_status == "unknown"
    assert unknown.medication_list_status == "unknown"
    assert unknown.allergies == [] and unknown.medications == []
    assert "Allergy status not supplied" in unknown.missing_information
    assert "Current medication list not supplied" in unknown.missing_information


def test_conflicting_medicine_statements_do_not_create_current_medicine():
    context = clarifier().process("Takes amlodipine but stopped amlodipine last week.")
    assert context.medication_list_status == "conflicting"
    assert {statement.status for statement in context.medication_statements} == {"current", "stopped"}
    assert context.medications == []
    assert "Current medication list requires confirmation" in context.missing_information

    mixed = clarifier().process("Stopped amlodipine but takes lisinopril.")
    assert [item.text for item in mixed.medications] == ["lisinopril"]
    assert {(item.name, item.status) for item in mixed.medication_statements} == {
        ("amlodipine", "stopped"), ("lisinopril", "current")}


def test_missing_observations_are_not_assumed_normal():
    context = clarifier().process("A 55-year-old adult diagnosed with hypertension. No known drug allergies. Takes no medications.")
    assert context.blood_pressure_readings == []
    assert context.labs == []
    assert context.pregnancy_status == "unknown"
    assert "Blood pressure reading not supplied" in context.missing_information
    assert "Renal function result not supplied" in context.missing_information
    assert "Potassium result not supplied" in context.missing_information
    assert "Pregnancy status not supplied for medication safety" in context.missing_information
    assert "Current medication list not supplied" not in context.missing_information


def test_hypertension_treatment_stays_conditional_when_required_facts_are_missing():
    context = clarifier().process("A 55-year-old adult diagnosed with hypertension.")
    fusion = ClinicalFusion()
    fusion.llm.generate_json = lambda *args, **kwargs: {
        "diagnoses": [{"diagnosis": "Hypertension", "confidence": 0.5,
                       "treatment_considerations": ["Start amlodipine"]}],
        "diagnostic_claims": [], "investigations_to_consider": [],
        "treatment_options_if_confirmed": [{
            "text": "Amlodipine may be discussed as a conditional option",
            "applies_to": "Hypertension", "conditions": ["Diagnosis confirmed"],
        }],
        "missing_information": [],
    }
    retrieval = OrchestratorResult(graph_results=GraphRetrievalResult(candidate_diseases=[], paths=[]),
                                   vector_results=VectorRetrievalResult())
    result = fusion.fuse(context, retrieval, [], [])
    assert result.diagnoses[0].treatment_considerations == []
    treatment = next(claim for claim in result.claims if claim.claim_type == "treatment")
    assert treatment.status == "unverified"
    assert "Allergy status not supplied" in treatment.missing_checks
    assert "Diagnosis or condition confirmed: Hypertension" in treatment.conditions
    report = ReportGenerator().generate(context, result.diagnoses, [], [], context.missing_information,
                                        0.5, [], claims=result.claims)
    assert report.ranked_diagnoses[0].treatment_considerations == []
    assert report.claims[0].status == "unverified"


def test_unanchored_model_allergy_is_rejected_and_conflicting_allergy_is_visible():
    parsed = {"symptoms": [], "conditions": [], "medications": [], "safety_flags": [],
              "allergy_statements": [{"substance": "penicillin", "source_phrase": "allergic to penicillin"}]}
    context = clarifier(parsed).process("No known drug allergies. Takes no medications.")
    assert context.allergy_status == "no_known_allergies"
    assert context.allergies == []

    conflict = clarifier().process("No known drug allergies, but allergic to penicillin.")
    assert conflict.allergy_status == "conflicting"
    assert conflict.allergies[0].text == "penicillin"
    assert any("Conflicting allergy" in flag for flag in conflict.safety_flags)


def test_retry_preserves_original_patient_facts_and_report_missingness(monkeypatch):
    extractor = clarifier()

    class Orchestrator:
        def retrieve(self, context):
            return OrchestratorResult(graph_results=GraphRetrievalResult(candidate_diseases=[], paths=[]),
                                      vector_results=VectorRetrievalResult())

    class Ranker:
        def rank(self, *args):
            return []

    class Detector:
        def detect(self, *args):
            return []

    class Fusion:
        def fuse(self, *args):
            return FusionResult([], [], [], [])

    class Confidence:
        calls = 0

        def evaluate(self, *args):
            self.calls += 1
            return (0.1, "retry") if self.calls == 1 else (0.5, "stop")

    class Retry:
        max_retries = 1

        def should_retry(self, attempt, action):
            return attempt < self.max_retries and action == "retry"

        def generate_feedback(self, *args):
            return "Synthetic feedback: stopped amlodipine"

        def expand_context(self, context):
            context.expanded_query = context.raw_input
            return context

    monkeypatch.setattr(routes, "get_pipeline", lambda: {
        "clarifier": extractor, "orchestrator": Orchestrator(), "ranker": Ranker(),
        "detector": Detector(), "fusion": Fusion(), "confidence": Confidence(),
        "retry": Retry(), "report": ReportGenerator(),
    })
    case = "Confirmed hypertension. Clinic BP 150/95. Takes amlodipine. No known drug allergies."
    result = routes.analyze_case(routes.AnalyzeRequest(case_text=case))
    assert result["patient_context"]["raw_input"] == case
    assert result["patient_context"]["medication_list_status"] == "reported"
    assert result["patient_context"]["medications"][0]["text"] == "amlodipine"
    assert result["patient_context"]["allergy_status"] == "no_known_allergies"
    assert "Pregnancy status not supplied for medication safety" in result["report"]["missing_information"]
