"""Conservative extraction of safety facts from the original patient statement.

Only explicit, quoted facts become current medicines, allergies, or observations.
Unclear statements remain unknown for clinician review.
"""

import re
from typing import Any

from backend.schemas.patient import BloodPressureReading, MedicationStatement


NO_ALLERGY = re.compile(r"\b(?:no known (?:drug |medication |medicine )?allergies|NKDA|NKA|denies (?:drug )?allergies)\b", re.I)
ALLERGY = re.compile(r"\b(?:allergic to|allergy to|allergies to|allergies:)\s+([A-Za-z][A-Za-z0-9-]*)", re.I)
ALLERGY_SUFFIX = re.compile(r"\b([A-Za-z][A-Za-z0-9-]*)\s+allergy\b", re.I)
NO_MEDICATION = re.compile(r"\b(?:no (?:current )?medications|takes? no medications|not taking any medications|medications?:\s*none)\b", re.I)
CURRENT_MEDICATION = re.compile(r"\b(?:takes?|taking|currently on|current medications?\s*(?:include|are|:)|medications?:)\s+([^.;\n]+)", re.I)
STOPPED_MEDICATION = re.compile(r"\b(?:stopped|discontinued|no longer taking|no longer takes?|not taking)\s+(?:taking\s+)?([^.;\n]+)", re.I)
BP = re.compile(r"\b(?:BP|blood pressure)\s*(?:is|was|of|:)?\s*(\d{2,3})\s*/\s*(\d{2,3})(?:\s*mm\s*Hg)?", re.I)
NEGATIVE_PREGNANCY = re.compile(r"\b(?:not pregnant|nonpregnant|denies pregnancy|pregnancy test negative)\b", re.I)
PREGNANCY = re.compile(r"\bpregnant\b", re.I)
CONFIRMED_HYPERTENSION = re.compile(r"\b(?:diagnosed with|confirmed|known|history of)\s+hypertension\b|\bhypertension diagnosis confirmed\b", re.I)
RULED_OUT_HYPERTENSION = re.compile(r"\bhypertension (?:ruled out|excluded)\b", re.I)
LAB_PATTERNS = {
    "egfr": re.compile(r"\b(?:eGFR|estimated glomerular filtration rate)\s*(?:is|of|:|=)?\s*(\d+(?:\.\d+)?)\b", re.I),
    "potassium": re.compile(r"\b(?:serum )?potassium\s*(?:is|of|:|=)?\s*(\d+(?:\.\d+)?)\b", re.I),
    "creatinine": re.compile(r"\b(?:serum )?creatinine\s*(?:is|of|:|=)?\s*(\d+(?:\.\d+)?)\b", re.I),
}


def _anchored_quote(raw_text: str, quote: str) -> str | None:
    if not quote:
        return None
    match = re.search(re.escape(quote), raw_text, re.I)
    return match.group(0) if match else None


def _medication_names(clause: str):
    clause = re.split(r"\b(?:but|however|though|while|because|after|before|then)\b", clause, maxsplit=1, flags=re.I)[0]
    for part in re.split(r",|\band\b", clause, flags=re.I):
        match = re.match(r"\s*(?:the\s+)?([A-Za-z][A-Za-z0-9-]*)", part)
        if match and match.group(1).casefold() not in {"no", "any", "none", "a", "an", "the"}:
            yield match.group(1), part.strip()


def extract_safety_facts(raw_text: str, parsed: dict[str, Any]) -> dict[str, Any]:
    """Return explicit facts and missingness; never infer a normal finding from silence."""
    safety_flags: list[str] = []
    missing: list[str] = []

    no_allergy = NO_ALLERGY.search(raw_text)
    allergy_mentions: list[tuple[str, str]] = []
    for pattern in (ALLERGY, ALLERGY_SUFFIX):
        for match in pattern.finditer(raw_text):
            preceding = raw_text[max(0, match.start() - 14):match.start()].casefold()
            if preceding.endswith("not ") or "no known " in preceding or match.group(1).casefold() in {"drug", "medication", "medicine"}:
                continue
            allergy_mentions.append((match.group(1), match.group(0)))
    for item in parsed.get("allergy_statements", []):
        if not isinstance(item, dict):
            continue
        name, quote = item.get("substance"), item.get("source_phrase")
        anchored = _anchored_quote(raw_text, quote) if isinstance(quote, str) else None
        if (isinstance(name, str) and anchored
                and re.search(rf"\b{re.escape(name)}\b", quote, re.I)
                and not NO_ALLERGY.search(quote)
                and (ALLERGY.search(quote) or ALLERGY_SUFFIX.search(quote))):
            allergy_mentions.append((name, anchored))
    allergy_mentions = list(dict.fromkeys((name.casefold(), quote) for name, quote in allergy_mentions))
    if no_allergy and allergy_mentions:
        allergy_status = "conflicting"
        safety_flags.append("Conflicting allergy statements require confirmation")
    elif allergy_mentions:
        allergy_status = "allergies_reported"
    elif no_allergy:
        allergy_status = "no_known_allergies"
    else:
        allergy_status = "unknown"
        missing.append("Allergy status not supplied")

    statements: list[MedicationStatement] = []
    for pattern, status in ((CURRENT_MEDICATION, "current"), (STOPPED_MEDICATION, "stopped")):
        for match in pattern.finditer(raw_text):
            preceding = raw_text[max(0, match.start() - 14):match.start()].casefold()
            if status == "current" and re.search(r"(?:was|previously|used to|had been|stopped|not|no longer)\s+$", preceding):
                continue
            for name, _ in _medication_names(match.group(1)):
                statements.append(MedicationStatement(name=name, status=status,
                                                      source_phrase=match.group(0), extraction_certainty="explicit"))
    for item in parsed.get("medication_statements", []):
        if not isinstance(item, dict):
            continue
        name, quote, status = item.get("name"), item.get("source_phrase"), item.get("status")
        anchored = _anchored_quote(raw_text, quote) if isinstance(quote, str) else None
        if not (isinstance(name, str) and isinstance(quote, str) and status in {"current", "stopped", "uncertain"}
                and anchored and re.search(rf"\b{re.escape(name)}\b", quote, re.I)):
            continue
        cue = CURRENT_MEDICATION if status == "current" else STOPPED_MEDICATION if status == "stopped" else None
        if cue is None or (cue.search(quote) and (status != "current" or not STOPPED_MEDICATION.search(quote))):
            statements.append(MedicationStatement(name=name, status=status, source_phrase=anchored,
                                                  extraction_certainty="explicit" if cue else "uncertain"))
    # Legacy medicine names without an assertion are retained as uncertain mentions.
    for name in parsed.get("medications", []):
        if isinstance(name, str) and re.search(rf"\b{re.escape(name)}\b", raw_text, re.I):
            if not any(s.name.casefold() == name.casefold() for s in statements):
                statements.append(MedicationStatement(name=name, status="uncertain",
                                                      source_phrase=name, extraction_certainty="uncertain"))
    statements = list({(s.name.casefold(), s.status, s.source_phrase.casefold()): s for s in statements}.values())
    by_name: dict[str, set[str]] = {}
    for statement in statements:
        by_name.setdefault(statement.name.casefold(), set()).add(statement.status)
    conflicting_names = {name for name, statuses in by_name.items() if "current" in statuses and "stopped" in statuses}
    no_medications = NO_MEDICATION.search(raw_text)
    if conflicting_names or (no_medications and any(s.status == "current" for s in statements)):
        medication_status = "conflicting"
        safety_flags.append("Conflicting medication statements require confirmation")
        missing.append("Current medication list requires confirmation")
    elif any(s.status == "current" for s in statements):
        medication_status = "reported"
    elif no_medications:
        medication_status = "none_reported"
    else:
        medication_status = "unknown"
        missing.append("Current medication list not supplied")
    current_medications = [s for s in statements if s.status == "current" and s.name.casefold() not in conflicting_names]
    if no_medications:
        current_medications = []

    readings: list[BloodPressureReading] = []
    for match in BP.finditer(raw_text):
        systolic, diastolic = int(match.group(1)), int(match.group(2))
        if not (50 <= systolic <= 300 and 30 <= diastolic <= 200):
            continue
        before = raw_text[max(0, match.start() - 30):match.start()]
        method_cues = list(re.finditer(r"\b(home|ambulatory|ABPM|clinic|office)\b", before, re.I))
        cue = method_cues[-1].group(1).casefold() if method_cues else ""
        method = "ambulatory" if cue in {"ambulatory", "abpm"} else "clinic" if cue in {"clinic", "office"} else "home" if cue == "home" else "unknown"
        readings.append(BloodPressureReading(systolic_mm_hg=systolic, diastolic_mm_hg=diastolic,
                                             method=method, source_phrase=match.group(0)))

    negative_pregnancy = NEGATIVE_PREGNANCY.search(raw_text)
    positive_pregnancy = [m for m in PREGNANCY.finditer(raw_text)
                          if not (negative_pregnancy and negative_pregnancy.start() <= m.start() < negative_pregnancy.end())]
    if negative_pregnancy and positive_pregnancy:
        pregnancy_status = "conflicting"
        safety_flags.append("Conflicting pregnancy statements require confirmation")
    elif positive_pregnancy:
        pregnancy_status = "pregnant"
    elif negative_pregnancy:
        pregnancy_status = "not_pregnant"
    else:
        pregnancy_status = "unknown"

    confirmed = CONFIRMED_HYPERTENSION.search(raw_text)
    ruled_out = RULED_OUT_HYPERTENSION.search(raw_text)
    hypertension_confirmed = True if confirmed and not ruled_out else False if ruled_out and not confirmed else None
    if confirmed and ruled_out:
        safety_flags.append("Conflicting hypertension diagnosis statements require confirmation")

    labs = []
    for name, pattern in LAB_PATTERNS.items():
        for match in pattern.finditer(raw_text):
            unit_match = re.match(r"\s*(mmol/L|mEq/L|mg/dL|µmol/L|umol/L|mL/min(?:/1\.73\s*m2)?)\b",
                                  raw_text[match.end():], re.I)
            labs.append({"name": name, "value": float(match.group(1)),
                         "unit": unit_match.group(1) if unit_match else None,
                         "source_phrase": raw_text[match.start():match.end() + (unit_match.end() if unit_match else 0)],
                         "extraction_certainty": "explicit"})

    hypertension_scope = bool(re.search(r"\b(?:hypertension|high blood pressure)\b", raw_text, re.I) or readings)
    if hypertension_scope:
        if not readings:
            missing.append("Blood pressure reading not supplied")
        elif all(reading.method == "unknown" for reading in readings):
            missing.append("Blood pressure measurement setting not supplied")
        if hypertension_confirmed is None:
            missing.append("Hypertension diagnosis confirmation not supplied")
        if pregnancy_status == "unknown":
            missing.append("Pregnancy status not supplied for medication safety")
        if not any(lab["name"] in {"egfr", "creatinine"} for lab in labs):
            missing.append("Renal function result not supplied")
        if not any(lab["name"] == "potassium" for lab in labs):
            missing.append("Potassium result not supplied")
        for lab in labs:
            if lab["unit"] is None:
                missing.append(f"Unit for {lab['name']} result not supplied")

    return {
        "allergy_status": allergy_status,
        "allergy_source_phrase": no_allergy.group(0) if no_allergy else allergy_mentions[0][1] if allergy_mentions else None,
        "allergy_mentions": allergy_mentions,
        "medication_statements": statements,
        "medication_list_status": medication_status,
        "current_medications": current_medications,
        "blood_pressure_readings": readings,
        "pregnancy_status": pregnancy_status,
        "pregnancy_source_phrase": negative_pregnancy.group(0) if negative_pregnancy else positive_pregnancy[0].group(0) if positive_pregnancy else None,
        "hypertension_confirmed": hypertension_confirmed,
        "hypertension_source_phrase": confirmed.group(0) if confirmed else ruled_out.group(0) if ruled_out else None,
        "labs": labs,
        "missing_information": missing,
        "safety_flags": safety_flags,
        "hypertension_scope": hypertension_scope,
    }
