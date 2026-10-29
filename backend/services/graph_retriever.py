from neo4j import GraphDatabase
from typing import List, Dict, Any
from backend.schemas.retrieval import GraphRetrievalResult, GraphPath
from backend.schemas.patient import PatientContext

class GraphRetriever:
    def __init__(self, kg_path: str):
        # kg_path is ignored now as we connect to Neo4j directly
        self.uri = "bolt://localhost:7687"
        self.auth = ("neo4j", "password")
        try:
            self.driver = GraphDatabase.driver(self.uri, auth=self.auth)
            self.is_ready = True
        except Exception as e:
            print(f"Failed to connect to Neo4j: {e}")
            self.is_ready = False

    def retrieve(self, context: PatientContext) -> GraphRetrievalResult:
        if not self.is_ready:
            return GraphRetrievalResult(candidate_diseases=[], paths=[])

        symptom_names = [s.normalized_name.lower() for s in context.symptoms if s.normalized_name]
        drug_names = [d.normalized_name.lower() for d in context.medications if d.normalized_name]

        candidate_diseases: Dict[str, Dict[str, Any]] = {}
        paths: List[GraphPath] = []
        contraindications: List[Dict[str, Any]] = []

        with self.driver.session() as session:
            # 1. Phenotype to Disease
            if symptom_names:
                query = """
                MATCH (s:Node)-[r]->(d:Node {type: 'disease'})
                WHERE s.name IN $symptoms AND toLower(type(r)) CONTAINS 'phenotype'
                RETURN s.name AS x_name, s.type AS x_type, d.name AS y_name, d.type AS y_type, type(r) AS relation, d.id AS y_id
                """
                result = session.run(query, symptoms=symptom_names)
                for record in result:
                    disease_name = record['y_name']
                    if disease_name not in candidate_diseases:
                        candidate_diseases[disease_name] = {
                            "name": disease_name,
                            "id": record['y_id'],
                            "score": 0.0,
                            "evidence_count": 0
                        }
                    candidate_diseases[disease_name]["evidence_count"] += 1
                    candidate_diseases[disease_name]["score"] += 1.0

                    paths.append(GraphPath(
                        nodes=[{"name": record['x_name'], "type": record['x_type']}, {"name": record['y_name'], "type": record['y_type']}],
                        relationships=[record['relation']],
                        score=1.0
                    ))

            # 2. Contraindications for current drugs
            if drug_names:
                query = """
                MATCH (drug:Node)-[r]->(disease:Node)
                WHERE drug.name IN $drugs AND toLower(type(r)) CONTAINS 'contraindication'
                RETURN drug.name AS x_name, disease.name AS y_name
                """
                result = session.run(query, drugs=drug_names)
                for record in result:
                    contraindications.append({
                        "drug": record['x_name'],
                        "disease": record['y_name']
                    })

        sorted_candidates = sorted(list(candidate_diseases.values()), key=lambda x: x["score"], reverse=True)

        return GraphRetrievalResult(
            candidate_diseases=sorted_candidates[:10],
            paths=paths,
            contraindications=contraindications,
            drug_interactions=[],
            limitations=["Using Live Neo4j Graph Database for retrieval."]
        )
