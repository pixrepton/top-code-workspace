"""Diagnose RAG pipeline — check each stage inside the container."""
import sys, json, os
sys.path.insert(0, '/app/backend')

import config
import chromadb
from chromadb.config import Settings as ChromaSettings

# Use chroma_clean (ENV override)
chroma_path = getattr(config, 'CHROMA_DB_DIR', '/app/chroma_clean')
print('Chroma path:', chroma_path)

client = chromadb.PersistentClient(path=chroma_path, settings=ChromaSettings(anonymized_telemetry=False))
collections = client.list_collections()
print('Collections:', [(c.name, c.count()) for c in collections])

# Get hvac_knowledge
col = client.get_collection('hvac_knowledge')
total = col.count()
print('hvac_knowledge total chunks:', total)

# Test queries
queries = [
    'Jakie sa warunki dofinansowania Czyste Powietrze 2025 dla pompy ciepla?',
    'Jaka moc pompy ciepla Panasonic polecasz do domu 180m2 z 2005 roku?',
    'Wymagania elektryczne dla pompy ciepla powietrze-woda 9-12kW',
    'Czy kociol gazowy Viessmann moze pracowac jako backup z pompa ciepla?',
    'Orientacyjny koszt instalacji pompy ciepla powietrze-woda w Polsce 2025'
]

for q in queries:
    print()
    print('=== Query:', q[:60], '... ===')
    results = col.query(query_texts=[q], n_results=5)
    n = len(results['ids'][0])
    print('Results found:', n)
    if n > 0:
        for i in range(n):
            dist = results['distances'][0][i] if results['distances'] else 0
            meta = results['metadatas'][0][i] if results['metadatas'] else {}
            doc = results['documents'][0][i][:200] if results['documents'] else ''
            fname = meta.get('filename', meta.get('source', '?'))
            chunk_id = results['ids'][0][i][:20]
            print('  %d: dist=%.4f file=%s id=%s' % (i+1, dist, fname, chunk_id))
            print('    text: %s' % doc[:150])
    else:
        print('  ZERO results from Chroma!')

# Check BM25
print()
print('=== BM25 check ===')
try:
    from engine import RAGEngine
    engine = RAGEngine()
    if engine.bm25:
        print('BM25 is ready')
        # Test BM25 search
        bm25_scores = engine.bm25.get_scores(queries[0])
        top_bm25 = sorted(enumerate(bm25_scores), key=lambda x: -x[1])[:5]
        print('BM25 top scores:', [(idx, round(score, 4)) for idx, score in top_bm25 if score > 0])
    else:
        print('BM25 is NOT ready (None)')
except Exception as e:
    print('BM25 error:', str(e)[:200])

# Check sensitivity distribution
print()
print('=== SENSITIVITY DISTRIBUTION ===')
all_data = col.get(limit=total)
sensitivities = {}
for m in all_data['metadatas']:
    if m:
        s = m.get('sensitivity', m.get('document_sensitivity', 'unknown'))
        sensitivities[s] = sensitivities.get(s, 0) + 1
print('Sensitivity:', sensitivities)

# Check document count from registry
print()
print('=== DOC REGISTRY ===')
reg_path = chroma_path + '/doc_registry.json'
if os.path.isfile(reg_path):
    with open(reg_path) as f:
        reg = json.load(f)
    versions = reg.get('versions', {})
    active = sum(1 for v in versions.values() if v.get('status') == 'active')
    print('Registry versions:', len(versions))
    print('Active documents:', active)
