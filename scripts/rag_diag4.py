"""Diagnose RAG step by step."""
import sys, json, time
sys.path.insert(0, '/app/backend')

import config
from engine import RAGEngine

print('Config CHROMA_DB_DIR:', config.CHROMA_DB_DIR)

engine = RAGEngine()
start = time.time()

print('Querying engine...')
result = engine.query('Jakie sa warunki dofinansowania Czyste Powietrze 2025 dla pompy ciepla?')
elapsed = time.time() - start
print('Elapsed: %.2fs' % elapsed)

# Write result to file for inspection
with open('/tmp/rag_result.json', 'w') as f:
    json.dump({k: str(v)[:500] for k, v in result.items()}, f, indent=2, ensure_ascii=False)

print()
print('Result keys:', list(result.keys()))
print('Answer:', result.get('answer', '')[:200])
print('Sources:', len(result.get('sources', [])))
print('Chunks used:', len(result.get('chunks_used', [])))
print('Trace:', result.get('_trace', [])[:3])
print('Pipeline debug:', result.get('pipeline_debug', {}))

chunks = result.get('chunks_used', [])
if chunks:
    for c in chunks[:3]:
        md = c.get('metadata', {})
        print()
        print('  Chunk:', md.get('filename', '?'), 'text:', c.get('text', '')[:150])
else:
    print('NO CHUNKS!')

    # Try to find what's happening with internal retrieval
    if hasattr(engine, 'hybrid_search'):
        print()
        print('Testing internal hybrid_search...')
        try:
            candidates = engine.hybrid_search('Czyste Powietrze 2025 pompa ciepla')
            print('Candidates:', len(candidates))
        except Exception as e:
            print('hybrid_search failed:', str(e)[:200])
