"""Test RAGEngine.query() to find where results disappear."""
import sys, json
sys.path.insert(0, '/app/backend')

from engine import RAGEngine

engine = RAGEngine()
print('BM25 ready:', engine.bm25 is not None)

result = engine.query('Jakie sa warunki dofinansowania Czyste Powietrze 2025 dla pompy ciepla?')
print()
print('Answer:', result.get('answer', '')[:300])
print('Chunks used:', len(result.get('chunks_used', [])))
print('Sources:', len(result.get('sources', [])))
print('_trace stages:', [t.get('stage') for t in result.get('_trace', [])])

# See what's in gating
print()
print('Pipeline debug:', json.dumps(result.get('pipeline_debug', {}), ensure_ascii=False, indent=2)[:500])

chunks = result.get('chunks_used', [])
if chunks:
    for c in chunks[:3]:
        md = c.get('metadata', {})
        print()
        print('Chunk:', md.get('filename', '?'), 'text:', c.get('text', '')[:150])
