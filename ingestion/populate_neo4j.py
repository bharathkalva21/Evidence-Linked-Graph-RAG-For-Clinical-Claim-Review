from neo4j import GraphDatabase
import pandas as pd
import argparse
import os
import time

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=50000, help="Number of rows to ingest")
    args = parser.parse_args()

    URI = "bolt://localhost:7687"
    AUTH = ("neo4j", "password")

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    kg_path = os.path.join(base_dir, "datasets", "kg.csv")

    print(f"Reading {kg_path}...")
    if args.limit:
        df = pd.read_csv(kg_path, nrows=args.limit)
    else:
        df = pd.read_csv(kg_path)

    # Basic cleaning to match our cypher queries expectations
    df['x_name'] = df['x_name'].astype(str).str.lower()
    df['y_name'] = df['y_name'].astype(str).str.lower()
    # Ensure relation is a valid cypher identifier (no spaces)
    df['relation'] = df['relation'].astype(str).str.replace(' ', '_').str.upper()

    print(f"Connecting to Neo4j to insert {len(df)} edges...")
    # Wait for Neo4j to be ready
    for _ in range(30):
        try:
            driver = GraphDatabase.driver(URI, auth=AUTH)
            driver.verify_connectivity()
            break
        except Exception:
            time.sleep(1)
    else:
        print("Neo4j did not start in time.")
        return

    def create_edges_by_type(tx, relation, batch):
        query = f"""
        UNWIND $batch AS row
        MERGE (x:Node {{id: row.x_id}})
        ON CREATE SET x.name = row.x_name, x.type = row.x_type
        MERGE (y:Node {{id: row.y_id}})
        ON CREATE SET y.name = row.y_name, y.type = row.y_type
        MERGE (x)-[:`{relation}`]->(y)
        """
        tx.run(query, batch=batch)

    with driver.session() as session:
        session.run("CREATE INDEX IF NOT EXISTS FOR (n:Node) ON (n.id)")
        session.run("CREATE INDEX IF NOT EXISTS FOR (n:Node) ON (n.name)")

        grouped = df.groupby('relation')
        total = 0
        for relation, group in grouped:
            records = group.to_dict('records')
            batch_size = 5000
            for i in range(0, len(records), batch_size):
                batch = records[i:i+batch_size]
                session.execute_write(create_edges_by_type, relation, batch)
                total += len(batch)
                print(f"Inserted {total} edges...")

    driver.close()
    print("Neo4j Ingestion complete!")

if __name__ == "__main__":
    main()
