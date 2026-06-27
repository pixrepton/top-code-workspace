"""Test Chroma query directly using the correct embedding model."""
import sys, json
sys.path.insert(0, '/app/backend')

import config
print('Chroma path:', config.CHROMA_DB_DIR)
print('Embedding model:', getattr(config, 'EMBEDDING_MODEL_NAME', 'N/A'))

import chromadb
from chromadb.config import Settings as ChromaSettings

client = chromadb.PersistentClient(path=str(config.CHROMA_DB_DIR), settings=ChromaSettings(anonymized_telemetry=False))
col = client.get_collection('hvac_knowledge')
total = col.count()
print('Total chunks:', total)

# Get the embedding function from the config
from sentence_transformers import SentenceTransformer
model_name = getattr(config, 'EMBEDDING_MODEL_NAME', 'intfloat/multilingual-e5-base')
print('Loading embedding model:', model_name)
model = SentenceTransformer(model_name)
print('Model dim:', model.get_sentence_embedding_dimension())

# Encode query
query = 'Jakie sa warunki dofinansowania Czyste Powietrze 2025 dla pompy ciepla?'
print('Encoding query...')
query_embedding = model.encode(query).tolist()
print('Query embedding dim:', len(query_embedding))

# Query Chroma directly with embedding
print('Querying Chroma with 768-dim embedding...')
results = col.query(query_embeddings=[query_embedding], n_results=5, include=['documents', 'metadatas', 'distances'])
print('Results found:', len(results['ids'][0]))
for i in range(len(results['ids'][0])):
    dist = results['distances'][0][i]
    meta = results['metadatas'][0][i]
    doc = results['documents'][0][i][:200]
    print('  %d: dist=%.4f file=%s' % (i+1, dist, meta.get('filename', '?')))
    print('    text: %s' % doc[:150])
