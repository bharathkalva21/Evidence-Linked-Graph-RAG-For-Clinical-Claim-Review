# Detailed architecture diagram

This diagram maps the implemented `/analyze` path, the two evidence trust levels, local data ingestion, and the synthetic evaluation harness. It represents the current research prototype; it does not imply clinical validation.

```mermaid
flowchart TB
    subgraph Interface["A. Interface and API"]
        Clinician["Clinician or researcher"] --> UI["Browser UI: frontend/app.js at /ui"]
        UI -->|POST case_text| API["FastAPI: backend/api/routes.py"]
    end

    subgraph Context["B. Patient context"]
        Clarifier["ClinicalClarifier: structured extraction"]
        FactRules["patient_fact_extractor.py: anchor safety facts to input"]
        Linker["OntologyParser + EntityLinker: normalize terms"]
        Patient["PatientContext: facts, source phrases, unknowns"]
        Clarifier --> FactRules --> Patient
        Clarifier --> Linker --> Patient
        Terms[(HPO, MONDO, DrugCentral names)] --> Linker
    end

    subgraph Retrieval["C. Retrieval orchestrator"]
        Orchestrator["RetrievalOrchestrator"]
        GraphR["GraphRetriever"] --> GraphDB[(Neo4j biomedical graph)]
        TextR["VectorRetriever: textbook"] --> TextDB[(Qdrant textbooks)]
        AuthorityR["VectorRetriever: authoritative"] --> AuthorityDB[(Qdrant guidelines + labels)]
        DrugR["DrugCentralService"] --> DrugData[(Local target interactions)]
        SearchR["EvidenceScannerAgent"] --> Serper["Optional Serper search"]
        Orchestrator --> GraphR
        Orchestrator --> TextR
        Orchestrator --> AuthorityR
        Orchestrator --> DrugR
        Orchestrator --> SearchR
        GraphR --> Leads["Candidate signals: not verified citations"]
        TextR --> Leads
        DrugR --> Leads
        SearchR --> Leads
        AuthorityR --> Passages["SourcePassage IDs + dated sections"]
    end

    subgraph Reasoning["D. Candidate generation"]
        Ranker["EvidenceRanker: heuristic ordering"]
        InitialConflicts["ConflictDetector: graph leads and gaps"]
        Fusion["ClinicalFusion: diagnoses and claim proposals"]
        Normalize["claim_synthesis.py: normalize evidence IDs"]
        Ranker --> InitialConflicts --> Fusion --> Normalize
    end

    subgraph Verification["E. Independent evidence gate"]
        Verifier["ClaimVerifier: exact pinned-passage and scope checks"]
        Safety["ConflictDetector: narrow amlodipine label rules"]
        Checked["ClinicalClaim: supported, conflicting, or unverified"]
        Verifier --> Safety --> Checked
        Manifest["Versioned source manifest: URL, version, date, SHA-256"] --> Verifier
        Snapshots[(Local NICE + DailyMed snapshots)] --> Verifier
    end

    subgraph Delivery["F. Retry and report"]
        Confidence["ConfidenceEvaluator: uncalibrated retry heuristic"]
        Retry["AdaptiveRetry: expand query, re-read original case"]
        Report["ReportGenerator + ClinicalReport schema"]
        Review["Differential, conditional options, warnings, gaps, exact links"]
        Confidence -->|report| Report --> Review
        Confidence -.->|retry up to two times| Retry
    end

    subgraph Ingestion["G. Local ingestion, outside request path"]
        KGCSV["Biomedical KG CSV"] --> NeoImport["populate_neo4j.py"] --> GraphDB
        Book["MedQA textbook text"] --> TextImport["populate_qdrant.py"] --> TextDB
        Official["Official NICE and DailyMed URLs"] --> SourceImport["authoritative_sources.py: fetch, hash, parse, embed"] --> AuthorityDB
        Manifest --> SourceImport
        SourceImport --> Snapshots
    end

    subgraph Evaluation["H. Synthetic evaluation, separate from indexed sources"]
        Cases["cases.v1.json: six synthetic cases"] --> Runner["evaluation/run.py"]
        Runner -->|calls analysis route function| API
        Runner -.->|swaps retrieval mode only| Orchestrator
        Runner --> Artifacts["Metrics, case errors, provenance, blinded review packet"]
    end

    API --> Clarifier
    Clarifier -.->|JSON generation| LLM["LLMFallback: Gemini, Cohere, Mistral, OpenRouter"]
    Fusion -.->|JSON generation| LLM
    Patient --> Orchestrator
    Orchestrator --> Leads
    Orchestrator --> Passages
    Leads --> Ranker
    Patient --> InitialConflicts
    Patient --> Fusion
    Patient --> Safety
    Patient --> Report
    Passages --> Fusion
    Passages --> Verifier
    Passages --> Report
    Normalize --> Verifier
    InitialConflicts --> Confidence
    Checked --> Confidence
    Checked --> Report
    Retry -.->|original case + expanded retrieval query| Clarifier
    Review --> API
    API -->|JSON response| UI
```

## Reading the diagram

1. **Solid arrows** show request data or local ingestion. **Dotted arrows** show external model calls, evaluation substitution, or the optional retry loop. The evaluation runner invokes the existing route function directly; it does not create a second production API.
2. **Candidate signals** from the graph, textbook retrieval, DrugCentral, and Serper can influence proposals but cannot make a claim `supported`. Only pinned `SourcePassage` records are eligible for citation. Their IDs and full passage data must match the manifest-backed local snapshot.
3. **The independent gate** leaves general diagnostic, investigation, and treatment proposals `unverified` when semantic support or patient applicability cannot be established. Explicit, narrow amlodipine safety rules can create a source-backed warning or a conflicting treatment claim. An absent source or unknown patient fact leads to a gap or abstention.
4. **The confidence value** controls retries and is not a calibrated probability. The UI presents statuses and missing checks; clinicians must assess the report and sources. Raw case text is sent to configured LLM providers, so the local prototype should be demonstrated with synthetic or appropriately de-identified inputs.

For file-level explanations and source limitations, see [ARCHITECTURE.md](ARCHITECTURE.md). For copyable inputs and observed failure cases, see [SAMPLE_CASES.md](SAMPLE_CASES.md).
