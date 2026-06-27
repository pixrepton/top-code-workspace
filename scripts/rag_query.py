"""Query the RAG endpoint and print structured results."""
import urllib.request
import json
import sys

def query_rag(question):
    payload = {
        'query': question,
        'stream': False,
        'use_cache': False
    }
    req = urllib.request.Request(
        'http://localhost:8000/api/chat',
        data=json.dumps(payload).encode(),
        headers={'Content-Type': 'application/json'},
        method='POST'
    )
    try:
        resp = urllib.request.urlopen(req, timeout=120)
        data = json.loads(resp.read())
        answer = data.get('answer', '')
        citations = data.get('citations', [])
        first_sentence = answer.split('.')[0] if '.' in answer else answer[:200]

        print("=== ANSWER (first sentence) ===")
        print(first_sentence[:500])
        print()
        print("=== TOP SOURCES ===")
        for i, c in enumerate(citations[:2]):
            print(f'{i+1}. display_name: {c.get("display_name","?")} | page: {c.get("page","?")} | page_range: {c.get("page_range","?")} | doc_type: {c.get("doc_type","?")}')
            print(f'   stable_doc_id: {c.get("stable_doc_id","?")} | doc_version_id: {c.get("doc_version_id","?")}')
        print()
        print(f'Sources count: {len(citations)}')
        print(f'Full answer length: {len(answer)} chars')
        print("=" * 50)
        return {
            'answer_first_sentence': first_sentence,
            'sources': citations[:2],
            'sources_count': len(citations),
            'answer_length': len(answer),
            'full_answer': answer
        }
    except urllib.error.HTTPError as e:
        err = e.read().decode()[:500]
        print(f'HTTP {e.code}: {err}')
        return {'error': f'HTTP {e.code}: {err}'}
    except Exception as e:
        print(f'ERROR: {e}')
        return {'error': str(e)}

if __name__ == '__main__':
    questions = [
        "Jakie są warunki dofinansowania Czyste Powietrze 2025 dla pompy ciepła?",
        "Jaką moc pompy ciepła Panasonic polecasz do domu 180m2 z 2005 roku?",
        "Wymagania elektryczne dla pompy ciepła powietrze-woda 9-12kW",
        "Czy kocioł gazowy Viessmann może pracować jako backup z pompą ciepła?",
        "Orientacyjny koszt instalacji pompy ciepła powietrze-woda w Polsce 2025"
    ]

    results = {}
    for i, q in enumerate(questions, 1):
        print(f'\n\n=== Q{i}: {q[:60]}... ===')
        results[f'Q{i}'] = query_rag(q)

    # Summary
    print("\n\n=== SUMMARY ===")
    for key, val in results.items():
        if 'error' in val:
            print(f'{key}: ERROR - {val["error"]}')
        else:
            print(f'{key}: {val["sources_count"]} sources, answer_len={val["answer_length"]}')
