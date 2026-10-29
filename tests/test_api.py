import pytest
from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)

def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "CDSS Backend"}

def test_analyze_endpoint():
    payload = {
        "case_text": "A 58-year-old man with diabetes and hypertension presents with crushing chest pain radiating to the left arm, sweating, nausea, and shortness of breath. He takes metformin and lisinopril. No known drug allergies."
    }
    response = client.post("/analyze", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "patient_context" in data
    assert "report" in data
    assert "Myocardial Infarction" in data["report"]["ranked_diagnoses"][0]["diagnosis"]
