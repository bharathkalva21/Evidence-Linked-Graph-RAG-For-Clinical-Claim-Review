# Local data needed to run the prototype

This repository intentionally contains **code, metadata, and synthetic fixtures only**. Large biomedical files, database volumes, API keys, and raw guideline/label snapshots are ignored by Git. Obtain each dataset from its publisher under its own terms; do not copy patient records into this tree. The paths below reflect what the current scripts actually load, rather than a proposed future data inventory.

## Required local inputs

| Local path | Used by | Source / note |
| --- | --- | --- |
| `datasets/ontologies/hpo/hp.obo` | `OntologyParser`, entity linking | [Human Phenotype Ontology releases](https://github.com/obophenotype/human-phenotype-ontology/releases) |
| `datasets/ontologies/mondo/mondo.obo` | `OntologyParser`, entity linking | [Mondo OBO download](https://mondo.monarchinitiative.org/pages/download/) |
| `datasets/drugcentral/structures.smiles.tsv` | Drug-name lookup in `OntologyParser` | [DrugCentral downloads](https://www.drugcentral.org/download) |
| `datasets/drugcentral/drug.target.interaction.tsv.gz` | `DrugCentralService` | [DrugCentral downloads](https://www.drugcentral.org/download); keep the compressed TSV name expected by the code |
| `datasets/kg.csv` | `ingestion/populate_neo4j.py` | [PrimeKG project and data instructions](https://github.com/mims-harvard/PrimeKG); use a CSV with the expected `relation`, `x_id`, `x_type`, `x_name`, `y_id`, `y_type`, and `y_name` columns |
| `datasets/literature/MedQA/MedQA-USMLE/textbooks/en/First_Aid_Step1.txt` | `ingestion/populate_qdrant.py` | [MedQA project](https://github.com/jind11/MedQA); textbook availability and reuse terms must be checked separately |
| `datasets/authoritative/hypertension/` | Pinned source parser and verifier | Exact snapshots fetched from official URLs in [the source manifest](../sources/hypertension/manifest.json) |

The local evaluator also requires populated Neo4j and Qdrant stores. Extra MedQA question files, MedMCQA, PubMedQA, MedBullets, and the full DrugCentral SQL dump are **not loaded by the current `/analyze` route**. Keeping them outside a fresh checkout avoids implying they are needed for this prototype.

## Build the local stores

After placing the files above and installing `requirements.txt`:

```bash
./run_qdrant.sh
./run_neo4j.sh
python ingestion/populate_neo4j.py --limit 50000
python ingestion/populate_qdrant.py
python -m ingestion.authoritative_sources fetch
python -m ingestion.authoritative_sources verify
python -m ingestion.authoritative_sources ingest
```

The two Docker scripts create development containers with local ports and a fixed Neo4j password. If those containers already exist, start the existing containers rather than running the creation scripts again. `populate_neo4j.py` defaults to the first 50,000 graph rows; `--limit 0` requests the complete CSV and may require substantial storage and time. `populate_qdrant.py` currently indexes only the first 150,000 characters of one textbook, not the entire MedQA corpus. Both indexes must be rebuilt when their underlying data or embedding method changes.

## Pinned authoritative sources

`sources/hypertension/manifest.json` records document IDs, versions, dates, approved URLs, selected sections, jurisdictions, reuse notes, and SHA-256 hashes for a NICE recommendations snapshot and one DailyMed amlodipine SPL label. `fetch` saves raw bytes only when the official download matches the exact pinned checksum. `verify` reparses the local bytes, and `ingest` updates dedicated guideline and label Qdrant collections. The report verifier checks retrieved passage identity against the same local snapshots.

If a publisher has changed its live page or label since the pinned version, `fetch` will fail. This is intentional: review the new source, its clinical scope and terms, then version the manifest and reindex. Do not silently substitute changed bytes or cite a search snippet as a guideline. Because raw snapshots are not redistributed here, exact reproduction of an earlier run requires retaining the corresponding local snapshots separately in accordance with their rights.

## Evaluation separation and limitations

The frozen synthetic case set is in `evaluation/cases.v1.json`, outside the ingestion paths. Do not index its cases, reference diagnoses, or reviewer labels. Generated run outputs live under ignored `evaluation/runs/`; preserve a run manifest and captured results if reporting its metrics. The repository's source manifest has **pending independent clinician review**, and its England guideline and United States drug label have different jurisdictions. Dataset access or citation provenance alone does not establish clinical validity or treatment eligibility.
