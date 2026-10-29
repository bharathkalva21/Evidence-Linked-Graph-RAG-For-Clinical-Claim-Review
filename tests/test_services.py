import pytest
from backend.services.entity_linker import EntityLinker
from backend.agents.clarifier import ClinicalClarifier

def test_entity_linker():
    lookup_table = {
        "chest pain": [{"id": "HP:01", "source": "HPO", "name": "Chest Pain"}],
        "diabetes": [{"id": "MONDO:01", "source": "MONDO", "name": "Diabetes Mellitus"}]
    }
    linker = EntityLinker(lookup_table)
    
    # Exact match
    linked = linker.link("chest pain", "symptom")
    assert linked.normalized_name == "Chest Pain"
    assert linked.confidence == 1.0
    
    # Fuzzy match
    linked = linker.link("chest pains", "symptom")
    assert linked.normalized_name == "Chest Pain"
    assert linked.confidence > 0.8
    
    # No match
    linked = linker.link("random words here", "symptom")
    assert linked.normalized_name is None
    
def test_clarifier():
    lookup_table = {
        "chest pain": [{"id": "HP:01", "source": "HPO", "name": "Chest Pain"}]
    }
    linker = EntityLinker(lookup_table)
    clarifier = ClinicalClarifier(linker)
    
    text = "A 58-year-old man presents with chest pain."
    context = clarifier.process(text)
    
    assert context.age == 58
    assert context.sex == "male"
    assert len(context.safety_flags) == 1
    assert "chest pain" in context.safety_flags[0]
    
    assert len(context.symptoms) == 1
    assert context.symptoms[0].text == "chest pain"
    assert context.symptoms[0].normalized_name == "Chest Pain"
