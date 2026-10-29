#!/bin/bash
echo "Starting Qdrant Vector Database..."
docker run -d -p 6333:6333 -p 6334:6334 -v qdrant_data:/qdrant/storage --name qdrant qdrant/qdrant
echo "Qdrant is running on http://localhost:6333"
