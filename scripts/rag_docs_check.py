"""Check RAG knowledge base contents with auth."""
import urllib.request
import json

admin_key = 'R-qo2dBXP-Qk-TFjtPuY0m2VlQ1tcpvbbgo2Ogs76Ms'
headers = {'Authorization': 'Bearer %s' % admin_key}

# Try /documents
req = urllib.request.Request('http://localhost:8000/documents', headers=headers)
try:
    resp = urllib.request.urlopen(req, timeout=10)
    data = json.loads(resp.read())
    print('=== /documents ===')
    print(json.dumps(data, indent=2, ensure_ascii=False)[:5000])
except urllib.error.HTTPError as e:
    body = e.read().decode()[:1000]
    print('HTTP %d: %s' % (e.code, body))
except Exception as e:
    print('ERROR: %s' % e)

# Try /diagnostics/kb
print('\n=== DIAGNOSTICS KB ===')
req = urllib.request.Request('http://localhost:8000/diagnostics/kb', headers=headers)
try:
    resp = urllib.request.urlopen(req, timeout=10)
    data = json.loads(resp.read())
    print(json.dumps(data, indent=2, ensure_ascii=False)[:3000])
except urllib.error.HTTPError as e:
    body = e.read().decode()[:1000]
    print('HTTP %d: %s' % (e.code, body))
except Exception as e:
    print('ERROR: %s' % e)

# Try /diagnostics/retrieval to check CP2025 docs
print('\n=== DIAGNOSTICS RETRIEVAL (Czyste Powietrze) ===')
req = urllib.request.Request('http://localhost:8000/diagnostics/retrieval?q=Czyste+Powietrze+2025+pompa+ciepla', headers=headers)
try:
    resp = urllib.request.urlopen(req, timeout=30)
    data = json.loads(resp.read())
    print(json.dumps(data, indent=2, ensure_ascii=False)[:3000])
except urllib.error.HTTPError as e:
    body = e.read().decode()[:1000]
    print('HTTP %d: %s' % (e.code, body))
except Exception as e:
    print('ERROR: %s' % e)
