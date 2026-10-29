from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    DATASETS_DIR: str = "datasets"
    HPO_PATH: str = "datasets/ontologies/hpo/hp.obo"
    MONDO_PATH: str = "datasets/ontologies/mondo/mondo.obo"
    KG_PATH: str = "datasets/kg.csv"
    DRUGCENTRAL_DIR: str = "datasets/drugcentral"
    MEDQA_DIR: str = "datasets/literature/MedQA"
    MEDMCQA_DIR: str = "datasets/literature/MedMCQA"
    PUBMEDQA_DIR: str = "datasets/literature/pubmedqa-master/pubmedqa-master"
    MEDBULLETS_DIR: str = "datasets/literature/medbulltes5op"

    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "password"

    QDRANT_URL: str = "http://localhost:6333"
    VECTOR_COLLECTION_TEXTBOOKS: str = "medical_textbooks"
    VECTOR_COLLECTION_PUBMEDQA: str = "pubmedqa_contexts"
    VECTOR_COLLECTION_MEDQA: str = "medqa_train"
    VECTOR_COLLECTION_GUIDELINES: str = "clinical_guidelines"
    VECTOR_COLLECTION_DRUG_LABELS: str = "clinical_drug_labels"

    OPENROUTER_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    COHERE_API_KEY: str = ""
    MISTRAL_API_KEY: str = ""
    SERPER_API_KEY: str = ""

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[1] / ".env",
        extra="ignore",
    )

settings = Settings()
