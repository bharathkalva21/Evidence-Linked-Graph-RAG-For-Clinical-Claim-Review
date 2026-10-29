import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.schemas.report import ClinicalReport
from backend.schemas.patient import PatientContext

client = TestClient(app)

def test_analyze_endpoint_empty_case():
    response = client.post("/analyze", json={"case_text": ""})
    assert response.status_code == 200
    data = response.json()
    assert "report" in data
    assert "ranked_diagnoses" in data["report"]
    assert "disclaimer" in data["report"]

def test_analyze_endpoint_simple_case():
    response = client.post("/analyze", json={"case_text": "I have a headache."})
    assert response.status_code == 200
    report_data = response.json().get("report", {})
    report = ClinicalReport(**report_data)
    assert report.overall_confidence >= 0.0
    assert len(report.disclaimer) > 0

def test_patient_context_schema():
    context = PatientContext(
        raw_input="headache and fever",
        symptoms=[],
        known_conditions=[],
        medications=[]
    )
    assert context.raw_input == "headache and fever"
    assert context.medications == []
