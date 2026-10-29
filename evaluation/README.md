# Step 8 evaluation

For the proposed full multi-condition benchmark, staged implementation, metric definitions, and paper reporting, see [MULTI_DISEASE_EVALUATION_PLAN.md](MULTI_DISEASE_EVALUATION_PLAN.md). The synthetic pilot and the separate MedQA exam-vignette pilot are exploratory subsets of that broader plan.

## Frozen medication-safety and provenance challenges (13 October 2026)

The [pre-run protocol](SAFETY_PROVENANCE_PROTOCOL.md) and [108 developer-labeled synthetic cases](med_safety_cases.v1.json) were committed before the benchmark. Nine strata have 12 cases each, including positive amlodipine allergy and current-simvastatin warnings, unknown/conflicting histories, stopped medication, different-drug allergy, lookalike names, and clean negatives. The two tested paths supply a **fixed proposed amlodipine option and all pinned label passages**; one uses intended structured facts and one runs the production deterministic safety-fact extractor on free text with empty model hints. Neither path is a full LLM-backed `/analyze` call or a source-retrieval evaluation. Independent clinician review of expected labels is pending.

| Measure | Structured facts | Deterministic text extraction |
| --- | ---: | ---: |
| Warning precision | 72/72 (1.000) | 68/68 (1.000) |
| Warning recall | 72/72 (1.000) | 68/72 (0.944) |
| Unexpected `supported` label-warning decisions | 0/168 | 0/168 |
| Unknown/conflicting-allergy abstention | 24/24 | 20/24 |

Four text-path unknown-allergy cases were missed because `No allergy history was recorded` was interpreted as an allergy mention. [The safety snapshot](../paper/MEDICATION_SAFETY_TEST_RESULTS.json) reports Wilson intervals, per-stratum counts, hashes, and failure IDs. Its 168 negative support opportunities represent case × two implemented label-warning types minus positive type decisions; within-case observations are correlated. These are provisional engineering results from source-derived cases, not patient safety estimates.

The provenance test accepted **26/26** valid source controls and rejected **132/132** constructed invalid citation/source checks (26 each for five one-factor mutation types, plus two wrong snapshot hashes). Rejection is based on invalid-citation and trusted-passage checks, not on ordinary claims being `unverified`. [The tamper snapshot](../paper/PROVENANCE_TAMPER_RESULTS.json) gives mutation-level counts. This test establishes behavior for the tested identity corruptions, not semantic support for treatment claims.

With the two local publisher snapshots available, rerun to **new** ignored output paths:

```bash
python -m evaluation.run_med_safety --output evaluation/runs/med-safety-new
python -m evaluation.run_provenance --output evaluation/runs/provenance-new
python -m evaluation.prepare_med_safety_review --output evaluation/runs/med-safety-review-new
```

Give qualified reviewers only the generated `review_packet.jsonl`, retaining `private_review_index.jsonl` separately; the [review rubric](SAFETY_LABEL_REVIEW.md) explains the required ratings. Do not label these results clinician-adjudicated until those ratings are completed and reconciled.

## Pinned-source retrieval metrics (13 October 2026)

The MedQA answer key does **not** label relevant guideline or label passages, so Precision@k, Recall@k, Hit@k, MRR, nDCG, context relevance, and context recall cannot be inferred from that exam run. A separate [frozen 10-query known-passage probe set](retrieval_probes.v1.json) tests the production authoritative-source retriever against its entire **26-passage pinned corpus** (17 NICE NG136 sections, 9 DailyMed amlodipine label chunks). The developer wrote the queries and source-section judgments from that same corpus before running retrieval. Grades are 2 for a direct-answer passage, 1 for related but insufficient, and 0 for all unlisted passages. Required fact IDs link to grade-2 passages. These are engineering labels, **not** blinded or clinician-adjudicated relevance judgments. The test does not cover textbook-vector or graph retrieval.

The retriever currently returns five guideline hits followed by five drug-label hits, without merging their scores into a global rank. All metrics use that **actual context order**. Binary Precision@k, Recall@k, Hit@k, and MRR count only grade-2 passages; graded nDCG uses gains `2^grade − 1` with a logarithmic rank discount. Precision@k divides by k, even if fewer than k passages are returned. Recall@k is restricted to **all developer-judged direct-answer passages within this 26-passage corpus**, not all relevant clinical literature. Context relevance is the fraction of the full retrieved context that is directly answer bearing; with ten passages per query here, it equals pooled Precision@10. Context recall is the fraction of 13 developer-listed required facts whose linked source passage appears anywhere in the full context. These context metrics are transparent annotation-based measures, not LLM-judge scores.

| Measure | @1 | @3 | @5 | @10 |
| --- | ---: | ---: | ---: | ---: |
| Precision@k | 6/10 (0.60) | 7/30 (0.233) | 8/50 (0.16) | 12/100 (0.12) |
| Micro Recall@k | 6/12 (0.50) | 7/12 (0.583) | 8/12 (0.667) | 12/12 (1.00) |
| Hit Rate@k | 6/10 (0.60) | 6/10 (0.60) | 6/10 (0.60) | 10/10 (1.00) |
| MRR@k | 0.600 | 0.600 | 0.600 | 0.667 |
| Mean nDCG@k | 0.600 | 0.495 | 0.529 | 0.670 |

All **10/10 retrieval queries completed**. Full-context relevance was **12/100** directly answer-bearing passages; required-fact coverage was **13/13**. The six guideline-focused queries placed a direct-answer passage at rank 1, while all four amlodipine-label queries placed theirs at rank 6 because the five guideline hits come first. The 13/13 fact coverage is expected to be optimistic for known-passage questions built from this small corpus; it is not evidence that real clinical cases receive all needed evidence. Median retrieval-only query time was 41.5 ms and p95 was 126.4 ms on this local run, excluding model initialization and network/provider generation. [The aggregate snapshot](../paper/RETRIEVAL_PROBE_RESULTS.json) gives exact denominators, per-query counters, source and output hashes, definitions, and unavailable generation metrics. Replaying the saved ordered source IDs produced a byte-identical `metrics.json`.

With the pinned snapshots and both Qdrant source collections ready, run and replay using fresh output paths:

```bash
python -m evaluation.run_retrieval --output evaluation/runs/retrieval-probes-v1
python -m evaluation.run_retrieval --replay evaluation/runs/retrieval-probes-v1/retrieval_records.jsonl --output evaluation/runs/retrieval-probes-v1-replay
python -m evaluation.summarize_retrieval --run evaluation/runs/retrieval-probes-v1 --replay-metrics evaluation/runs/retrieval-probes-v1-replay/metrics.json --output paper/RETRIEVAL_PROBE_RESULTS.json
```

Answer faithfulness, answer relevance and completeness, clinical task completion, and cost per query are **unavailable** here because no independent generated-answer judgments, workflow outcomes, or cost traces exist. The saved MedQA evaluation separately reports diagnosis answer agreement, completion, and end-to-end latency; citation identity is not semantic faithfulness.

## MedQA US test exam-vignette pilot (13 October 2026)

The local [MedQA](https://github.com/jind11/MedQA) USMLE `test.jsonl` file is an **exam question split**, not a patient-record dataset. The [adapter](medqa_adapter.py) requires SHA-256 `cfa75cbcc53c29b023752b0a395ff49d8202121041392735ae44771a5ec734a3` and scans its 1,273 rows. The frozen eligibility rule requires an exact terminal “most likely diagnosis?” prompt, a keyed answer equal to its answer option, at least 100 characters of vignette before that prompt, no literal answer in the vignette, and a recognized exam step. This yields 89 eligible cases: 27 Step 1 and 62 Step 2/3. Before seeing model outputs, SHA-256 sorting with seed `cdss-medqa-diagnosis-v1` selected 12 and 24 cases respectively. [The committed selection manifest](medqa_selection.v1.json) records the source hash, rules, counts, and zero-based source row indices. All 36 selected answer strings are distinct.

The adapter sends only the vignette stem to `/analyze`: answer choices, keyed answer, and terminal diagnosis question are withheld. The answer is available only to the scorer. It is a single exact normalized alias, so synonymous diagnoses can count as misses. This is **generative answer agreement** on a selected public examination subset, not multiple-choice accuracy, independent clinical diagnosis adjudication, or patient-case validation. The public test questions may also have appeared in provider training data; this cannot be ruled out. The pinned guideline and label corpus is limited to hypertension and amlodipine, so most selected questions are outside its supported source scope.

The 13 October run completed 108/108 case–mode analyses. Strict rank-1 agreement was 19/36 (LLM only), 12/36 (text RAG), and 14/36 (graph plus text); rank-3 agreement was 19/36, 13/36, and 14/36. Completed reports with no ranked diagnosis numbered 1, 8, and 13. The graph arm returned zero disease candidates for every exam case. Provider identity differed across modes for eight cases after Gemini Flash Lite rate limits and fallback to Gemini Flash, so these observed mode differences do not establish a retrieval effect. Citation identity matched 22/22 and 10/10 emitted uses in the two retrieval arms; clinical relevance was not adjudicated. [The aggregate result snapshot](../paper/MEDQA_EXAM_PILOT_RESULTS.json) contains per-step and overall denominators, descriptive Wilson intervals, provider counts, and run hashes without question text or answer keys. Replay of the saved results produced byte-identical `metrics.json`.

With the original MedQA test file in the documented local path, regenerate and run the frozen set:

```bash
python -m evaluation.medqa_adapter --output evaluation/runs/medqa-us-diagnosis-v1/cases.json
python -m evaluation.run --cases evaluation/runs/medqa-us-diagnosis-v1/cases.json --output evaluation/runs/medqa-us-diagnosis-v1-results --review-sample-size 1000
python -m evaluation.summarize_medqa --cases evaluation/runs/medqa-us-diagnosis-v1/cases.json --run evaluation/runs/medqa-us-diagnosis-v1-results --output paper/MEDQA_EXAM_PILOT_RESULTS.json
```

Use fresh output paths for reruns; both commands refuse to overwrite existing artifacts. Raw MedQA questions, derived vignette text, answer keys, and generated reports stay in ignored `evaluation/runs/`. Only the selection protocol, metadata, and aggregate result snapshot are committed. Warning sensitivity, retrieval Hit@k, claim-support accuracy, and unsafe-option rate cannot be estimated from these diagnosis answer keys.

## Four-condition synthetic diagnostic pilot (12 October 2026)

A **pilot subset** of that plan has now run on [12 author-built, diagnosis-withheld cases](cases.multidisease-pilot.v1.json): three each for hypertension, chronic asthma, type 2 diabetes, and GORD/dyspepsia. To rerun locally with the documented graph/vector services, pinned snapshots, and configured providers:

```bash
python -m evaluation.run --cases evaluation/cases.multidisease-pilot.v1.json --output evaluation/runs/new-multidisease-pilot --review-sample-size 1000
```

The 12 October run completed 36/36 analyses. Strict normalized exact-alias matches at rank 1 were 10/12 (LLM only), 9/12 (text RAG), and 10/12 (graph plus text); rank-3 counts were identical. [The versioned result snapshot](../paper/MULTIDISEASE_PILOT_RESULTS.json) provides disease-level counts, descriptive Wilson intervals, per-case rank-1 strings, provider traces, and hashes. The local graph returned zero disease candidates in all pilot cases; an audit found no phenotype-type relations for the current disease query. Two cases used different synthesis providers across modes, so differences between arms are not evidence of graph benefit. Citation identity matched 30/30 text-RAG and 26/26 graph-plus-text uses; semantic support was not adjudicated.

These cases have **provisional author-intended labels**, no clinician reference standard, no negative/mimic sample, and only three examples per condition. The application's pinned authoritative corpus still covers adult hypertension and one amlodipine label. The pilot contains no positive warning opportunities or independently labeled relevant passages, so warning sensitivity, retrieval Hit@k/Recall@k, claim-support precision, unsafe-option rate, and clinical diagnostic accuracy remain unavailable. The archived six-case fixture results below remain a separate safety/boundary engineering check.

## Historical six-case fixture evaluation

This is a reproducible **engineering evaluation on six hand-authored synthetic cases**, not a clinical validation set. Every reference diagnosis is stated in its case text. Top-k results measure recognition on these fixtures, not diagnostic performance on patients. The cases live outside the indexed textbook and pinned source corpus. The runner also checks that no case text appears verbatim in a pinned passage.

### Run

From the project root, with the documented Python dependencies and local Neo4j/Qdrant services configured:

```bash
python -m evaluation.run --output evaluation/runs/full-001
```

Each case is run through the same clarifier, fusion, verifier, safety detector, and report builder in three modes. `llm_only` removes graph and text retrieval; `text_rag` uses textbook vectors and pinned guideline/label passages; `graph_text` adds Neo4j graph retrieval to that text. Web discovery and DrugCentral are disabled in all modes so those changing sources cannot favor one arm. Case order is fixed; mode order rotates by case. The clarifier runs once per case and its context is reused in all three arms. The runner calls the existing `/analyze` implementation directly and does not change the production API.

The default retry count is zero to keep the comparison bounded. For a quick infrastructure check, use `--limit 1` with a distinct output path. A captured run can be rescored without provider calls:

```bash
python -m evaluation.run --replay evaluation/runs/full-001/case_results.jsonl --output evaluation/runs/full-001-rescore
```

The runner fails closed if the pinned source snapshots are missing or their checksums no longer match the manifest. A new run never overwrites an existing output directory. Generated runs are Git ignored; retain a run directory if reporting its numbers.

### Artifacts and interpretation

- `run_manifest.json`: dataset version/hash, source manifest hash and document dates, prompt hashes, configured model IDs, actual provider trace in each case result, Git commit and dirty state, run settings, and command. `openrouter/free` can change underlying models; the provider trace cannot resolve that model version.
- `metrics.json`: per-mode numerators, denominators, values, and reasons when a metric is unavailable. Failed runs are separate from successful-case metrics and appear in `failed_cases`.
- The metric file also flags cases where fallback selected different synthesis providers across modes. Those cases cannot support a clean retrieval-only comparison. A matching `openrouter/free` ID still does not guarantee the same underlying model.
- `case_results.jsonl`: per-case reports, retrieval, provider trace, and latency; may contain case details and must be handled as sensitive if real cases are ever used.
- `case_errors.jsonl`: diagnostic misses, missed or unexpected narrow warning types, bad citations, clinician-adjudicated unsupported claims or unsafe options, and run failures.
- `review_packet_blinded.jsonl`: shuffled claim text, case/context, and cited passages without mode or system status, for independent reviewers.
- `review_index_private.jsonl`: mapping from review IDs to mode and system status; do not give this to reviewers before adjudication.
- `review_disagreements.jsonl`: unresolved differences between reviewers.

Diagnostic top-1 and top-3 use exact normalized matches to the explicit reference aliases. Citation validity checks that each cited ID resolves to a passage whose full stored metadata and text match the pinned corpus. Warning sensitivity measures the three labeled fixture types (`amlodipine_allergy`, `amlodipine_simvastatin`, and `allergy_status_unconfirmed`); verified label-warning sensitivity uses the first two and requires `verification_status=supported`. False-positive rate counts warning-negative cases with either label warning. Claim abstention is the fraction marked `unverified`. Latency includes shared clarification plus each mode's analysis, and excludes process and model initialization.

Claim support accuracy, unsupported-claim rate, and unsafe-option rate remain **unavailable** until independent clinical adjudication. The scorer never infers those labels from the model's own status or from a citation. A citation can be valid while a claim is clinically false or inapplicable. For each sampled review item, collect two qualified reviewers' independent judgments in JSONL:

```json
{"review_id":"review_...","reviewer_id":"reviewer-a","support_label":"supported","option_safety_label":"uncertain"}
{"review_id":"review_...","reviewer_id":"reviewer-b","support_label":"supported","option_safety_label":"uncertain"}
```

Allowed support labels are `supported`, `unsupported`, and `uncertain`; option safety labels are `safe`, `unsafe`, and `uncertain`. For non-treatment claims use `uncertain` for option safety. Each reviewer should check cited source section, date, population, conditions, and patient facts, then record their answer independently. Unanimous two-reviewer items can be scored; disagreements are listed and excluded until a documented reconciliation. Use the resulting file with `--adjudications path/to/reviews.jsonl --replay ... --output ...`. Do not interpret synthetic fixture performance or provisional metrics as patient safety, calibrated probability, or outcome benefit.

### Source and design limits

The pinned corpus covers NICE NG136 recommendations for adult hypertension (England; snapshot updated 2026-02-26) and one DailyMed amlodipine label (United States; effective 2026-01-01). The source manifest records URLs, checksums, license notes, and sections. The two source jurisdictions differ. The medication rules cover only amlodipine sensitivity and its simvastatin interaction; other contraindications and interactions are untested. The synthetic set is tiny, contains mostly known hypertension, and includes a pregnancy and GERD boundary case. It has no clinician-selected differential diagnoses, real-world prevalence, complex missingness, prospective workflow, or patient outcomes. Independent clinician review of the source choices, case labels, claim support, and treatment safety remains pending.
