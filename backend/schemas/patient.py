from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Literal


AllergyStatus = Literal["unknown", "no_known_allergies", "allergies_reported", "conflicting"]
MedicationListStatus = Literal["unknown", "none_reported", "reported", "conflicting"]
PregnancyStatus = Literal["unknown", "pregnant", "not_pregnant", "conflicting"]

class LinkedEntity(BaseModel):
    text: str
    normalized_name: Optional[str] = None
    entity_type: str
    ontology_id: Optional[str] = None
    ontology_source: Optional[str] = None
    confidence: float = 0.0
    candidates: List[Dict[str, Any]] = Field(default_factory=list)
    source_phrase: Optional[str] = None
    extraction_certainty: Literal["explicit", "uncertain"] = "uncertain"


class MedicationStatement(BaseModel):
    name: str
    status: Literal["current", "stopped", "uncertain"]
    source_phrase: str
    extraction_certainty: Literal["explicit", "uncertain"] = "explicit"


class BloodPressureReading(BaseModel):
    systolic_mm_hg: int = Field(gt=0)
    diastolic_mm_hg: int = Field(gt=0)
    method: Literal["clinic", "home", "ambulatory", "unknown"] = "unknown"
    source_phrase: str
    extraction_certainty: Literal["explicit", "uncertain"] = "explicit"

class PatientContext(BaseModel):
    raw_input: str
    expanded_query: Optional[str] = None
    age: Optional[int] = None
    sex: Optional[str] = None
    symptoms: List[LinkedEntity] = Field(default_factory=list)
    known_conditions: List[LinkedEntity] = Field(default_factory=list)
    medications: List[LinkedEntity] = Field(default_factory=list)
    medication_statements: List[MedicationStatement] = Field(default_factory=list)
    medication_list_status: MedicationListStatus = "unknown"
    allergies: List[LinkedEntity] = Field(default_factory=list)
    allergy_status: AllergyStatus = "unknown"
    allergy_source_phrase: Optional[str] = None
    blood_pressure_readings: List[BloodPressureReading] = Field(default_factory=list)
    pregnancy_status: PregnancyStatus = "unknown"
    pregnancy_source_phrase: Optional[str] = None
    hypertension_confirmed: Optional[bool] = None
    hypertension_source_phrase: Optional[str] = None
    hypertension_scope: bool = False
    vitals: Dict[str, Any] = Field(default_factory=dict)
    labs: List[Dict[str, Any]] = Field(default_factory=list)
    missing_information: List[str] = Field(default_factory=list)
    safety_flags: List[str] = Field(default_factory=list)
