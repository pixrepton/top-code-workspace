"""Diagnose RAG pipeline from INSIDE the container using engine.query()."""
import sys, json
sys.path.insert(0, '/app/backend')

import config
print('CHROMA_DB_DIR:', config.CHROMA_DB_DIR)

# Use the RAG engine's own query to test
from engine import RAGEngine
from api.schemas.chat import ChatMessageRequest

engine = RAGEngine()
print('Engine collection count:', engine.collection.count() if engine.collection else 'NO COLLECTION')
print('BM25 ready:', engine.bm25 is not None)
print('Embedding model:', config.EMBEDDING_MODEL_NAME if hasattr(config, 'EMBEDDING_MODEL_NAME') else 'N/A')

# Check what model the engine uses for query
if hasattr(engine, '_embedding_model'):
    print('Engine embedding model:', type(engine._embedding_model).__name__)
if hasattr(engine, 'embedding_model'):
    print('Engine embedding:', type(engine.embedding_model).__name__)

# Try a query through the engine's normal path
result = engine.query(
    'Jakie sa warunki dofinansowania Czyste Powietrze 2025 dla pompy ciepla?',
    top_k=5,
    mode='hybrid',
)
print()
print('Query result keys:', list(result.keys()))
print('Sources count:', len(result.get('sources', result.get('chunks_used', []))))
print('Answer:', result.get('answer', '')[:200])

chunks = result.get('chunks_used', [])
for i, c in enumerate(chunks[:3]):
    md = c.get('metadata', {})
    print()
    print('  Chunk %d:' % (i+1))
    print('    filename:', md.get('filename', md.get('source', '?')))
    print('    doc_type:', md.get('doc_type', '?'))
    print('    text:', (c.get('text') or c.get('content', ''))[:150])
