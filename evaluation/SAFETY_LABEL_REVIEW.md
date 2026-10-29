# Independent review of synthetic medication-safety labels

The benchmark results are **developer-labeled** until qualified clinicians independently check the cases. Generate the label-blinded packet with:

```bash
python -m evaluation.prepare_med_safety_review --output evaluation/runs/med-safety-review-v1
```

Give reviewers only `review_packet.jsonl`, never `private_review_index.jsonl` or the system outputs before their ratings. The packet includes 108 shuffled case texts and the pinned amlodipine-label sections; it excludes the developer's expected labels. Reviewers should use the exact case text, source section, date, and patient facts. They should not infer undocumented allergies or current medicines.

For each review ID, record the reviewer ID, whether the case is clinically clear, the expected warning types (`amlodipine_allergy`, `amlodipine_simvastatin`, `allergy_status_unconfirmed`), which of those warrant a `supported` status from the provided label, and a short rationale. Use one JSONL row per reviewer per case, for example:

```json
{"review_id":"safety_review_001","reviewer_id":"reviewer-a","case_clear":true,"expected_warning_types":["amlodipine_allergy"],"supported_warning_types":["amlodipine_allergy"],"rationale":"Explicit current amlodipine exposure and reported amlodipine sensitivity; cited contraindication section applies."}
```

Two independent clinicians are preferred. Reconcile disagreements before calculating any **clinician-adjudicated** metrics, and preserve both original ratings plus the reason for each reconciliation. If a vignette is ambiguous, retain it in the denominator and mark it undecidable rather than silently dropping it. The local packet and completed ratings remain under ignored `evaluation/runs/`; the public paper should report reviewer qualifications, agreement, exclusions, reconciliations, and aggregate counts without assuming these synthetic cases represent real patients.
