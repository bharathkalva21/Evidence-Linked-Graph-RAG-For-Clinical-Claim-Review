#!/bin/bash
echo "Starting Neo4j Graph Database..."
docker run -d --name neo4j -p 7474:7474 -p 7687:7687 \
    -e NEO4J_AUTH=neo4j/password \
    -v neo4j_data:/data \
    neo4j:5.18.0
echo "Neo4j is starting. UI: http://localhost:7474 (neo4j/password)"
