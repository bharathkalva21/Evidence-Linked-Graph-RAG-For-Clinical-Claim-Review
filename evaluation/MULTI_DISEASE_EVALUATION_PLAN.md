# Multi-disease evaluation plan

**Status (13 October 2026):** exploratory four-condition synthetic and MedQA exam-vignette pilots plus a known-passage retrieval probe performed; the full clinician-adjudicated benchmark and clinical validation remain pending. Execute remaining numbered stages one at a time, record each result, and commit that stage before starting the next.

### Progress against this plan

- **Completed pilot subset:** 12 versioned diagnosis-withheld synthetic cases across four intended conditions; all 36 case–mode analyses completed. Strict per-disease alias counts, citation identity, provider traces, zero graph-candidate finding, and replay are documented in [the pilot result snapshot](../paper/MULTIDISEASE_PILOT_RESULTS.json) and both paper drafts. The current engineering suite passed 60 tests after the retrieval-probe additions.
- **Completed external exam-vignette subset:** a source-hash-locked, diagnosis-prompt selection of 36 MedQA US test questions was frozen before inference. All 108 case–mode analyses completed; strict keyed-answer rank-1 agreement was 19/36, 12/36, and 14/36, with more empty differentials in retrieval arms. The [selection manifest](medqa_selection.v1.json), [aggregate snapshot](../paper/MEDQA_EXAM_PILOT_RESULTS.json), and [method notes](README.md) document the procedure, per-step results, provider mismatch, zero graph candidates, and limits. These are exam questions, not patient cases.
- **Completed known-passage retrieval probe:** ten developer-authored source-section questions were judged against the full 26-passage pinned source set before retrieval. The [probe definitions](retrieval_probes.v1.json) and [aggregate snapshot](../paper/RETRIEVAL_PROBE_RESULTS.json) record P@k, micro/macro Recall@k, Hit@k, MRR@k, graded nDCG@k, full-context relevance, required-fact coverage, latency, and hashes. This is an engineering source-recovery check, not the planned independently labeled clinical retrieval gold set; textbook and graph retrieval remain unscored.
- **Partially completed stages 2, 4, 5, 7, and 8:** diagnostic-case schema, per-disease top-1/top-3 counts with descriptive Wilson intervals, live run, replay, and manuscript reporting. Provider fallback was **not** disabled; two cases had mismatched synthesis providers across modes. The local graph returned no phenotype-based disease candidates, so this pilot does not test graph benefit.
- **Still pending:** Stage 0 formal preregistered protocol and sample-size calculation; Stage 1 multi-disease pinned sources and labels; the planned 200-case set; independent clinical retrieval and claim adjudication across graph/text/source channels; positive multi-disease medication-safety cases; robustness and fault-injection matrix; a controlled fixed-model ablation. None of the exploratory probes completes these stages.

## 1. Aim and current starting point

Evaluate whether this clinician-facing, evidence-linked Graph-RAG prototype (1) ranks plausible diagnoses, (2) retrieves applicable evidence, (3) represents the strength and limits of each claim correctly, and (4) detects medication and scope hazards. Report results across several diseases rather than treating one hypertension result as general performance.

The existing [`cases.v1.json`](cases.v1.json) contains **six hand-authored synthetic engineering fixtures**: five hypertension cases and one known-GERD boundary case. Every reference diagnosis appears in the input. The present [`run.py`](run.py) compares `llm_only`, `text_rag`, and `graph_text`, and [`metrics.py`](metrics.py) scores exact diagnosis aliases, narrow warning types, citation identity, and other engineering outcomes. The existing [evaluation notes](README.md) describe the saved run and its limitations. These cases remain a smoke/regression suite; they cannot measure diagnostic accuracy on cases where the answer is unknown to the system.

The only pinned authoritative corpus today is [NICE NG136](https://www.nice.org.uk/guidance/ng136/chapter/Recommendations) for adult hypertension and one U.S. DailyMed amlodipine label. A retrieved ID proves provenance only when the stored passage matches the pinned snapshot; it does **not** prove that the claim is clinically true or applies to this patient. Automatically supported medication warnings currently cover only narrow amlodipine rules. All other proposed treatment and diagnostic claims need independent review before they can be counted as supported.

### Study questions and pre-specified endpoints

Before inspecting locked-set outputs, write a protocol stating the population, use setting, source jurisdiction, inclusion/exclusion criteria, candidate diseases, exact gold-label rules, the primary endpoint, sample-size/precision target, failure handling, statistical tests, and any minimum performance targets. Suggested **primary technical endpoints** are (a) clinician-adjudicated precision of displayed `supported` claims and (b) sensitivity for pre-specified critical warnings. Report diagnostic top-1/top-3 and evidence retrieval as key secondary endpoints. If no clinician adjudication is available, mark the primary endpoints **unavailable** and describe the study as a synthetic engineering evaluation only.

Do not treat model-produced percentages as calibrated probabilities. Do not call citation-ID validity “clinical accuracy.” Do not count a missing or failed result as a correct abstention.

## 2. Define the disease and source scope

Use a coherent adult outpatient scope for the first multi-disease study. Candidate strata are below; final source choice, versions, and applicable recommendations require clinical review before test-set lock.

| Stratum | Candidate guideline for management/evidence | Boundary to record |
| --- | --- | --- |
| Adult hypertension | [NICE NG136](https://www.nice.org.uk/guidance/ng136/chapter/Recommendations) | Existing pinned source; pregnancy and other specialist pathways have separate guidance. |
| Adult chronic asthma | [BTS/NICE/SIGN NG245](https://www.nice.org.uk/guidance/ng245/chapter/Recommendations) | Chronic diagnosis/management; acute severe exacerbation is a separate safety/out-of-scope stratum until suitable emergency guidance is pinned. |
| Type 2 diabetes in adults | [NICE NG28](https://www.nice.org.uk/guidance/ng28) | This is a management guideline; select an appropriate diagnostic reference standard separately before scoring diagnosis cases. |
| Adult GORD/dyspepsia | [NICE CG184](https://www.nice.org.uk/guidance/cg184/chapter/Recommendations) | Track alarm symptoms and chest-pain mimics; do not score a reflux answer as safe when urgent alternative assessment is required. |

Choose medication-label sources for the **specific drugs and interactions actually tested**. Record document ID, section, version/effective date, jurisdiction, URL, SHA-256, local snapshot path, and reuse terms. A U.S. drug label and an England guideline are different jurisdictions; report this explicitly and do not silently merge their prescribing rules. Do not add a disease to treatment/safety claims merely by adding case texts: its citable recommendations and relevant label rules must first be in the pinned corpus and tested for applicability.

## 3. Build two separate case cohorts

1. **Diagnostic cohort:** symptoms, signs, history, and available test results, with the final diagnosis **absent from the case text**. Include typical, atypical, mimic, and insufficient-information presentations. Clinicians define one or more acceptable diagnoses and the conditions under which they are acceptable. Avoid cases where a diagnosis requires an omitted confirmatory test unless the reference answer is “insufficient information.”
2. **Management/safety cohort:** diagnosis is explicitly confirmed, so the task is evidence-linked investigations, conditional treatment options, missing checks, contraindications, and warnings. Vary current medicines, allergies, pregnancy status, renal function, relevant observations, and missing data. Include cases where the correct behavior is to withhold a specific recommendation or refer outside the pinned scope.

For an initial *synthetic engineering* locked set, target **25 cases per disease per cohort** (4 diseases × 2 cohorts × 25 = 200), with a small separate pilot set for debugging. This is a planning target, **not** a clinically justified sample size. Reserve at least a few negative/mimic and missing-information cases per stratum; predefine their exact counts and avoid hand-picking easy examples after seeing outputs. A later clinician-reviewed study needs a sample-size calculation based on the desired confidence-interval width for its primary endpoint and enough positive warning events to estimate sensitivity. Report event denominators and wide intervals rather than hiding sparse warning strata.

Write cases from a rubric and source-independent vignette templates, then manually vary language and facts. Keep all case text out of the indexed corpus and prompts used as few-shot examples. Check exact duplicates and near-duplicates between pilot, development, and locked test splits. The synthetic set may exercise the software and expose failure modes, but it cannot establish patient-level diagnostic or prescribing safety.

### Proposed versioned case schema

Store inputs and labels separately so the runner passes **only** `case_text` to the application. Suggested fields:

```json
{
  "case_id": "asthma-dx-001",
  "cohort": "diagnostic",
  "disease_stratum": "adult_chronic_asthma",
  "split": "locked_test",
  "case_text": "Synthetic presentation without the final diagnosis",
  "gold": {
    "acceptable_diagnoses": ["clinician-specified label or explicit unknown"],
    "patient_facts": [{"field": "allergy_status", "value": "unknown"}],
    "relevant_source_passage_ids": [],
    "required_claims": [],
    "required_warning_types": [],
    "unsafe_options": [],
    "expected_scope": "in_scope"
  },
  "reference": {
    "source_version_ids": [],
    "adjudication_rationale": "",
    "reviewer_ids": []
  }
}
```

The example is a schema sketch, **not** a clinical test case. For management cases, `required_claims` must specify the source section and patient conditions that make each claim applicable. For diagnostic cases, gold labels must specify whether multiple diagnoses are acceptable and how uncertain cases are scored. Keep reviewer identity and any real clinical data in access-controlled files, not a public Git commit.

## 4. Implement in reviewable stages

Each stage ends with a small, separate Git commit and a short progress note in this file or an evaluation log. Stop after a stage if its exit criterion fails; record the failure instead of changing locked labels to suit the model.

| Stage | Work | Required exit artifact / check | Suggested commit |
| --- | --- | --- | --- |
| **0. Freeze protocol and baseline** | Record study questions, endpoints, definitions, source scope, split rules, case target, and current Git/source/model IDs. Preserve the six-case result as an engineering baseline. | Versioned protocol; no claims about unrun cases. | `docs(evaluation): freeze multi-disease protocol` |
| **1. Expand the pinned source layer** | Generalize [`ingestion/authoritative_sources.py`](../ingestion/authoritative_sources.py), currently tied to `sources/hypertension/manifest.json` and an `ng136-` parser prefix. Ensure loading several manifests cannot overwrite previously indexed passages. Update retriever/verifier source lookup and add disease/drug coverage without automatically upgrading LLM claims to `supported`. | All chosen snapshots hash-verified, parsed with section IDs, indexed once, round-trip retrieved, jurisdiction and dates retained; ingestion tests pass. | `feat(sources): pin multi-disease guidelines and labels` |
| **2. Add dataset and schema validation** | Keep the six-case fixture unchanged as a smoke set. Create pilot/development/locked diagnostic and management datasets, with gold labels hidden from runtime input. Remove [`run.py`](run.py)'s requirement that reference aliases occur in diagnostic `case_text`; make warning taxonomy data-driven instead of amlodipine-only. | Schema validator rejects leaked diagnosis fields, duplicate IDs, invalid source IDs, unsupported gold labels, and split leakage; disease/cohort counts published. | `feat(evaluation): add multi-disease cases and validation` |
| **3. Establish reference labels** | First, author synthetic gold labels for engineering tests and mark them provisional. Later, have two qualified reviewers independently label diagnosis acceptability, patient facts, relevant passages, claim applicability, warnings, and unsafe options; reconcile disagreements with recorded reasons. The later clinician pass is required before clinical-content endpoints are reported. | Reviewer rubric and provisional gold file now; later, blinded ratings, agreement summary, adjudicated gold file, and unresolved-item list. | `docs(evaluation): add adjudication rubric and labels` |
| **4. Capture fair, complete runs** | Extend [`run.py`](run.py) to save ordered retrieved passage IDs/graph candidates, final and intermediate claims, source versions, provider/model trace, prompt hash, failures, latency, token/cost data if available. Fix the synthesis model across paired modes; disable provider fallback for the primary retrieval ablation or exclude and report mismatched runs under a pre-specified rule. Test provider fallback separately. | Immutable run directory and manifest per experiment; replay reproduces scores; no silent changes to corpus or model. | `feat(evaluation): capture ranked retrieval and provenance` |
| **5. Implement metrics** | Extend [`metrics.py`](metrics.py) with the definitions in Section 5, per-disease/cohort/mode denominators, unavailable reasons, and confidence intervals. Add small tests with hand-calculated expected values, especially absent gold evidence and failed runs. | Metric fixtures pass; no “0%” substituted for an unavailable metric. | `feat(evaluation): score multi-disease and safety metrics` |
| **6. Run robustness and failure tests** | Test negation, paraphrases, conflicting facts, unknown allergies, drug synonyms/doses, missing labs, pregnancy, pediatric/out-of-scope input, stale source hashes, database outage, and provider failure. Keep deliberately unsafe medication scenarios in synthetic fixtures only. | Failure matrix with expected abstention/escalation behavior and observed errors. | `test(evaluation): add robustness and fault cases` |
| **7. Run paired ablations** | On the same locked cases, compare `llm_only`, `text_rag`, and `graph_text` using the same source snapshots, clarifier output, prompts, and synthesis model. Add verifier-on/off only as an offline research ablation; never expose unverified suggestions as verified. | Per-case paired outputs and comparison, including provider mismatch/failure counts. | `test(evaluation): record frozen ablation run` |
| **8. Analyze and report** | Score the untouched locked set once, calculate intervals and error categories, produce tables/plots and limitations, then update the manuscript with actual observed values. Revisions after inspection need a new dataset/run version and must be disclosed. | Reproducible paper bundle; manuscript numbers match saved artifacts. | `docs(paper): report multi-disease evaluation` |

### Why Stage 1 precedes treatment tests

The present source ingestion handles one hypertension manifest and a narrow label rule set. The graph and textbook retrieval can suggest candidates but do not certify a treatment. New asthma, diabetes, or GORD cases would otherwise create the appearance of a multi-disease treatment evaluation while most relevant claims have no authoritative, versioned evidence to check. Record source coverage by disease and claim type before calculating support rates.

Stages 4–8 can run with the provisional synthetic labels while clinician review is pending. In that pass, report engineering metrics (for example retrieval rank, citation identity, and agreement with the authored fixture labels), and leave clinician-dependent claim support and unsafe-option estimates unavailable. Once independent review is complete, create a **new, versioned analysis**; do not silently replace the published synthetic numbers.

## 5. Metric definitions and denominators

Pre-register exact matching rules, acceptable synonyms, the handling of `uncertain` labels, and whether failures count as misses. Publish **numerator, denominator, point estimate, and 95% interval** for every reported proportion. Show both per-disease values and a macro average (equal disease weight); also show pooled values and case counts. Do not merge diagnostic and management cohorts.

| Question | Metric | Unit and definition |
| --- | --- | --- |
| Does extraction preserve patient facts? | Field precision, recall, F1; unknown-status accuracy | Compare structured facts with adjudicated gold at field/value level; count explicit `unknown` separately from false negatives. |
| Does retrieval find the right evidence? | Hit@1/5/10, Recall@5/10, MRR, optional nDCG | Compare **ordered** retrieved passage IDs with independent relevant-passage labels. Hit@k is the fraction of cases with ≥1 relevant passage in top k; Recall@k is recovered relevant passages / all labeled relevant passages. MRR uses first relevant rank. Exclude “no applicable passage” cases from these denominators and report them separately. |
| Does diagnosis ranking include an acceptable answer? | Top-1 accuracy, Hit@3, per-disease sensitivity/recall | On the diagnostic cohort only: an output is correct if an adjudicated acceptable diagnosis appears at the specified rank. For a strict single-label subset, top-1 equals multiclass accuracy. Show confusion matrix; do not compute specificity unless explicit negative/reference labels permit it. |
| Are cited IDs real and claims supported? | Citation identity rate; citation relevance/applicability; supported-claim precision; required-claim recall | ID rate checks snapshot identity. Blinded reviewers judge whether the cited section actually supports the particular claim **for this patient**. Supported-claim precision = adjudicated supported displayed claims / all displayed `supported` claims with decidable labels. Required-claim recall needs a complete, independent gold inventory and semantic matching; rating only generated claims cannot estimate recall. Report unverified and conflicting claims separately. |
| Does the system catch safety hazards? | Warning sensitivity, warning PPV, false-positive rate; unsafe-option rate | Use pre-specified positive and negative warning opportunities, by warning type and disease. Sensitivity = detected / gold positive; PPV = true detections / displayed warnings. Count any displayed unsafe treatment option, including `unverified` ones, as a potential user-facing hazard; report both per-option and fraction of cases with ≥1 unsafe option. |
| Does the system express uncertainty? | Abstention rate, coverage, error among non-abstained outputs | Define what “abstained” means by claim type before testing. Evaluate whether out-of-scope and missing-data cases withhold inapplicable certainty. A displayed “85% confidence” is not a calibrated probability; Brier score/ECE require a separately defined probability target and calibration study. |
| Is the experiment operationally reproducible? | Completion rate, failure rate, median/p95 latency, fallback rate, cost | Count all attempted case-mode runs, including timeouts. Report exact provider/model and any fallback; separate deployment reliability tests from clinical-content tests. |

For simple case-level proportions, use Wilson or exact binomial 95% intervals. For correlated claim-level observations, resample **cases**, not individual claims, for a cluster bootstrap interval. Paired mode differences should use case-level paired comparisons and intervals; label any tests exploratory if the sample-size/statistical plan was not pre-registered. Sparse per-disease or warning cells should show counts and intervals, with no overinterpretation of percentages.

## 6. Test matrix and failure analysis

| Test set | What it establishes | Minimum report |
| --- | --- | --- |
| Six existing fixtures | Regression of current API/evaluation behavior | Pass/fail, current warning types, citation identity; **not** diagnostic accuracy. |
| Multi-disease diagnostic set | Ranking on presentations without stated diagnoses | Top-1, Hit@3, per-disease confusion, insufficient-information behavior. |
| Multi-disease management set | Evidence-linked conditional recommendations with known diagnoses | Claim precision/recall when adjudicated, source coverage, unsafe-option cases, warning sensitivity. |
| Retrieval gold set | Whether graph/text retrieval surfaces applicable source sections | Hit@k, Recall@k, MRR, source-specific misses. |
| Safety challenge set | Behavior under allergy, interaction, missing-data, and scope hazards | False negatives, unsafe options, abstention/escalation, per-hazard counts. |
| Perturbation set | Stability when clinical meaning stays the same or flips | Paired change rate for paraphrase; expected change for negation, altered allergy/medication/dose. |
| Fault-injection set | Graceful behavior when infrastructure or sources fail | Stale-hash rejection, outage/error rate, fallback trace, absence of falsely `supported` claims. |

Use an error taxonomy: extraction error; retrieval miss; wrong/irrelevant citation; incorrect source applicability; diagnosis rank miss; missed warning; unsafe recommendation; overconfident/unverified wording; out-of-scope handling; provider or service failure. For each error, retain the case ID, disease, mode, source section, and reviewer rationale so the paper can explain *why* performance differs across diseases.

### Paper table template (fill only after the frozen run)

| Disease | Cohort | n attempted / complete | Top-1 | Hit@3 | Evidence Hit@5 | Supported-claim precision | Critical-warning sensitivity | Cases with unsafe option |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Hypertension | Diagnostic / management | — | — | — | — | — | — | — |
| Chronic asthma | Diagnostic / management | — | — | — | — | — | — | — |
| Type 2 diabetes | Diagnostic / management | — | — | — | — | — | — | — |
| GORD/dyspepsia | Diagnostic / management | — | — | — | — | — | — | — |

Cells that do not apply to a cohort should be shown as **N/A**, with a reason. Display the ablation modes in separate panels/tables rather than compressing three denominators into one cell. Include a flow diagram of included/excluded cases, per-disease confusion matrices, retrieval rank curves, safety error counts, and provider/failure audit in the supplement.

## 7. Publication and later clinical study

The first multi-disease run may support wording such as **“a reproducible, multi-condition synthetic evaluation of an evidence-linked Graph-RAG clinical decision support prototype”**, with explicit limits on source coverage and label provenance. It cannot establish clinical accuracy, safe prescribing, improved clinician decisions, or patient benefit. Put the protocol, dataset-generation rubric, source manifest, code commit, run manifests, annotation rubric, reviewer agreement/disagreements, per-disease denominators, confidence intervals, and failure examples in the paper or supplement. Do not select only favorable diseases or cases for the main table.

For a subsequent diagnostic-accuracy study with independent reference standards, use the [STARD-AI reporting guideline](https://www.nature.com/articles/s41591-025-03953-8) as a reporting checklist. If the system is later evaluated **live in a clinical workflow**, use [DECIDE-AI](https://www.nature.com/articles/s41591-022-01772-9) for that early clinical evaluation. Neither checklist turns synthetic fixture results into clinical validation. Before real case collection or live use, establish appropriate ethics, privacy, source licensing, clinician oversight, and data governance.
