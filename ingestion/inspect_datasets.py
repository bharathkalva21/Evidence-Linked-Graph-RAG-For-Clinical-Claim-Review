import os
import sys

def check_file(path: str, name: str) -> bool:
    if os.path.exists(path):
        size_mb = os.path.getsize(path) / (1024 * 1024)
        print(f"✅ {name} found: {path} ({size_mb:.2f} MB)")
        return True
    else:
        print(f"❌ {name} missing: {path}")
        return False

def check_dir(path: str, name: str) -> bool:
    if os.path.exists(path) and os.path.isdir(path):
        files = len(os.listdir(path))
        print(f"✅ {name} found: {path} ({files} files)")
        return True
    else:
        print(f"❌ {name} missing or not a directory: {path}")
        return False

def main():
    print("Inspecting Datasets for Multi-Agent Graph-RAG CDSS...\n")
    
    datasets_dir = "datasets"
    if not check_dir(datasets_dir, "Base Datasets Directory"):
        print("Cannot proceed without base datasets directory.")
        sys.exit(1)

    print("\n--- Knowledge Graph ---")
    check_file(f"{datasets_dir}/kg.csv", "Biomedical KG (CSV)")

    print("\n--- Ontologies ---")
    check_file(f"{datasets_dir}/ontologies/hpo/hp.obo", "HPO Ontology")
    check_file(f"{datasets_dir}/ontologies/mondo/mondo.obo", "MONDO Ontology")

    print("\n--- DrugCentral ---")
    dc_dir = f"{datasets_dir}/drugcentral"
    if check_dir(dc_dir, "DrugCentral Directory"):
        check_file(f"{dc_dir}/FDA+EMA+PMDA_Approved.csv", "Approved Drugs CSV")
        check_file(f"{dc_dir}/drug.target.interaction.tsv", "Drug Targets TSV")
        check_file(f"{dc_dir}/drug.target.interaction.tsv.gz", "Drug Targets TSV (GZ)")
        check_file(f"{dc_dir}/structures.smiles.tsv", "Structures TSV")

    print("\n--- Literature & QA ---")
    lit_dir = f"{datasets_dir}/literature"
    if check_dir(lit_dir, "Literature Directory"):
        check_dir(f"{lit_dir}/MedQA", "MedQA Directory")
        check_dir(f"{lit_dir}/MedMCQA", "MedMCQA Directory")
        check_dir(f"{lit_dir}/pubmedqa-master", "PubMedQA Directory")
        check_dir(f"{lit_dir}/medbulltes5op", "MedBullets Directory")

    print("\nInspection complete.")

if __name__ == "__main__":
    main()
