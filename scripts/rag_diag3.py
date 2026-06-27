"""Diagnose RAG engine query inside container."""
import sys, json
sys.path.insert(0, '/app/backend')

from engine import RAGEngine

engine = RAGEngine()
print('Collection count:', engine.collection.count())

# query() signature is just query_text
result = engine.query(
    'Jakie sa warunki dofinansowania Czyste Powietrze 2025 dla pompy ciepla?'
)
print()
print('Result keys:', list(result.keys()))
print('Number of sources:', len(result.get('sources', [])))
print('Chunks used:', len(result.get('chunks_used', [])))
print()
print('Answer:', result.get('answer', '')[:300])

chunks = result.get('chunks_used', [])
if chunks:
    for i, c in enumerate(chunks[:3]):
        print()
        md = c.get('metadata', {})
        print('Chunk %d:' % (i+1))
        print('  filename:', md.get('filename', '?'))
        print('  text:', c.get('text', '')[:200])
else:
    print('NO CHUNKS returned from engine.query()!')
    
# Also check gating
print()
print('Gating info:', result.get('gating', result.get('kb_confidence', 'N/A')))
print('Pipeline debug:', json.dumps(result.get('pipeline_debug', {}), ensure_ascii=False)[:300])
