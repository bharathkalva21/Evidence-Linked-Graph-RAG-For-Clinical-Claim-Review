# Synthetic cases for a local demonstration

Paste a case into `http://localhost:8000/ui` or send it as `{"case_text":"..."}` to `POST /analyze`. These texts are also the frozen fixtures in [evaluation/cases.v1.json](evaluation/cases.v1.json). They are **engineering examples, not patient records or clinician-validated answer keys**.

The observations below come from one 2026-10-07 `graph_text` evaluation run. That ablation disables Serper and DrugCentral, while the ordinary `/analyze` route can use them. LLM/provider choices and retrieval state can change the output. Check the presence of source links, conditions, missing facts, and verification status rather than expecting identical prose or a fixed numerical rank.

## 1. Confirmed hypertension; no identified label warning

> A 57-year-old woman with confirmed hypertension currently takes amlodipine. She has no known drug allergies and reports no other current medications.

**Observed:** Hypertension ranked first; amlodipine appeared in current medicines; no amlodipine allergy or simvastatin warning appeared. The missing blood-pressure reading and unverified claim status remained visible. This is the simplest UI smoke case.

## 2. Known GERD outside the pinned source domain

> A 45-year-old man has a previously documented diagnosis of gastroesophageal reflux disease and reports burning in his chest after heavy meals. He takes a multivitamin and reports no known drug allergies.

**Observed:** Gastroesophageal reflux disease ranked first. Its diagnostic claim stayed `unverified` without an authoritative source citation because the pinned source set is for hypertension and amlodipine. This case checks that a plausible model output is not promoted to source-supported status.

## 3. Pregnancy boundary case

> A 30-year-old pregnant woman has a documented diagnosis of hypertension. She takes no medications and reports no known drug allergies.

**Observed:** Hypertension ranked first and no treatment option was generated. The report displayed limitations. **Known extraction issue:** despite “documented diagnosis,” the saved run marked hypertension confirmation as not supplied. This case is useful for checking the pregnancy boundary and documenting that error, not for demonstrating validated pregnancy guidance.

## 4. Amlodipine allergy warning

> A 62-year-old woman with previously diagnosed hypertension currently takes amlodipine. She reports that she is allergic to amlodipine.

**Observed:** A `supported` amlodipine allergy warning pointed to the pinned DailyMed contraindication passage. Hypertension appeared second rather than first in the differential. Check the dated label link and warning status; do not treat the diagnostic ranking as a passed test.

## 5. Amlodipine and simvastatin review

> A 59-year-old man with confirmed hypertension reports recurring headaches and currently takes amlodipine and simvastatin. He reports no known drug allergies.

**Observed:** Hypertension ranked first. The interaction warning appeared as `unverified` in the saved run, so the UI should show that status rather than a confirmed safety conclusion. The current implementation does not establish a patient-specific dose or treatment decision from this input.

## 6. Unknown allergy status: regression case

> A 64-year-old man with known hypertension currently takes amlodipine. His allergy history was not supplied.

**Expected engineering behavior:** Keep allergy status unknown and display `allergy_status_unconfirmed`.

**Observed failure:** The clarifier extracted “his” as an allergy substance, marked allergies as reported, and omitted the missing-allergy warning. This known failure is retained in the frozen set and [evaluation case errors](evaluation/README.md) so future changes can be assessed honestly. Do not use this example as a successful safety demonstration.

## What a useful review should check

For each response, confirm that the report distinguishes patient facts from model proposals, shows missing checks, links claims to exact source sections and dates when available, and does not render an unverified proposal as a cleared treatment. A correct source link alone does not establish diagnosis, patient applicability, or safe prescribing. A qualified clinician still needs to review any medical interpretation.
