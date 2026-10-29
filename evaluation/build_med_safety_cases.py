"""Deterministically build the frozen, developer-labeled amlodipine safety set."""

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "evaluation/med_safety_cases.v1.json"

ALLERGY_POSITIVE = (
    "Allergic to amlodipine.", "Allergy to amlodipine.",
    "Allergies: amlodipine.", "Amlodipine allergy.",
)
ALLERGY_NEGATIVE = (
    "No known drug allergies.", "NKDA.", "Denies drug allergies.",
)
NO_CURRENT_MEDICINES = (
    "No current medications.", "Takes no medications.", "Medications: none.",
)
CURRENT_SIMVASTATIN = (
    "Takes simvastatin.", "Taking simvastatin.",
    "Currently on simvastatin.", "Current medications include simvastatin.",
)
OTHER_ALLERGIES = (
    "penicillin", "aspirin", "amoxicillin", "ibuprofen", "azithromycin", "lisinopril",
    "metformin", "sulfonamide", "rosuvastatin", "atorvastatin", "clindamycin", "doxycycline",
)
LOOKALIKE_ALLERGIES = (
    "amiodarone", "amiloride", "amlodipina", "amlodipine-like", "amoxicillin", "amitriptyline",
)
LOOKALIKE_MEDICINES = (
    "simvastatine", "pravastatin", "atorvastatin", "rosuvastatin", "simethicone", "sitagliptin",
)


def make_case(group: str, index: int) -> dict:
    base = f"A {45 + index}-year-old adult has confirmed hypertension. Amlodipine is being considered. "
    positive_allergy = ALLERGY_POSITIVE[index % len(ALLERGY_POSITIVE)]
    negative_allergy = ALLERGY_NEGATIVE[index % len(ALLERGY_NEGATIVE)]
    no_medicines = NO_CURRENT_MEDICINES[index % len(NO_CURRENT_MEDICINES)]
    current_simvastatin = CURRENT_SIMVASTATIN[index % len(CURRENT_SIMVASTATIN)]
    allergy_status = "no_known_allergies"
    allergy_name = None
    medication_name = None
    medication_status = "none_reported"
    stopped = False
    expected = []
    if group == "amlodipine_allergy":
        details = [positive_allergy, no_medicines]
        allergy_status, allergy_name = "allergies_reported", "amlodipine"
        expected = ["amlodipine_allergy"]
    elif group == "simvastatin_interaction":
        details = [negative_allergy, current_simvastatin]
        medication_name, medication_status = "simvastatin", "reported"
        expected = ["amlodipine_simvastatin"]
    elif group == "both_warnings":
        details = [positive_allergy, current_simvastatin]
        allergy_status, allergy_name = "allergies_reported", "amlodipine"
        medication_name, medication_status = "simvastatin", "reported"
        expected = ["amlodipine_allergy", "amlodipine_simvastatin"]
    elif group == "unknown_allergy":
        details = [
            ("Allergy history was not supplied.", "Allergy information is unavailable.",
             "No allergy history was recorded.")[index % 3],
            no_medicines,
        ]
        allergy_status = "unknown"
        expected = ["allergy_status_unconfirmed"]
    elif group == "conflicting_allergy":
        details = [positive_allergy, negative_allergy, no_medicines]
        allergy_status, allergy_name = "conflicting", "amlodipine"
        expected = ["allergy_status_unconfirmed"]
    elif group == "different_drug_allergy":
        allergy_name = OTHER_ALLERGIES[index]
        details = [f"Allergic to {allergy_name}.", no_medicines]
        allergy_status = "allergies_reported"
    elif group == "stopped_simvastatin":
        details = [negative_allergy, "Stopped simvastatin.", no_medicines]
        medication_name, stopped = "simvastatin", True
    elif group == "lookalike_names":
        if index < 6:
            allergy_name = LOOKALIKE_ALLERGIES[index]
            details = [f"Allergic to {allergy_name}.", no_medicines]
            allergy_status = "allergies_reported"
        else:
            medication_name = LOOKALIKE_MEDICINES[index - 6]
            medication_status = "reported"
            details = [negative_allergy, f"Takes {medication_name}."]
    elif group == "clean_negative":
        details = [negative_allergy, no_medicines]
    else:
        raise ValueError(group)

    # Clause order changes without changing the prespecified reference state.
    if index % 2:
        details.reverse()
    statements = []
    if medication_name:
        statements.append({"name": medication_name,
                           "status": "stopped" if stopped else "current",
                           "source_phrase": f"{'Stopped' if stopped else 'Takes'} {medication_name}."})
    return {
        "case_id": f"medsafe-{group}-{index + 1:02d}",
        "stratum": group,
        "case_text": base + " ".join(details),
        "structured_facts": {
            "allergy_status": allergy_status,
            "allergies": ([{"text": allergy_name, "entity_type": "allergy",
                           "extraction_certainty": "explicit"}] if allergy_name else []),
            "medication_list_status": medication_status,
            "medication_statements": statements,
        },
        "expected_warning_types": expected,
        "expected_supported_warning_types": [name for name in expected if name != "allergy_status_unconfirmed"],
        "expected_treatment_conflict": "amlodipine_allergy" in expected,
    }


def make_dataset() -> dict:
    groups = (
        "amlodipine_allergy", "simvastatin_interaction", "both_warnings",
        "unknown_allergy", "conflicting_allergy", "different_drug_allergy",
        "stopped_simvastatin", "lookalike_names", "clean_negative",
    )
    cases = [make_case(group, index) for group in groups for index in range(12)]
    assert len(cases) == 108 and len({case["case_id"] for case in cases}) == 108
    assert len({case["case_text"] for case in cases}) == 108
    return {
        "dataset_id": "medication-safety-amlodipine-synthetic",
        "dataset_version": "1.0.0",
        "case_count": len(cases),
        "label_status": "Developer-authored before execution; independent clinician review pending",
        "scope": "Proposed amlodipine; pinned label rules for sensitivity and current simvastatin only",
        "groups": {group: 12 for group in groups},
        "cases": cases,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"Output exists: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(make_dataset(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
