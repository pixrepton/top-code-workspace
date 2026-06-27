"""Check RAG document inventory and RAG readiness."""
import urllib.request
import json

# Check document inventory
req = urllib.request.Request('http://localhost:8000/knowledge/documents', headers={})
try:
    resp = urllib.request.urlopen(req, timeout=10)
    data = json.loads(resp.read())
    print(json.dumps(data, indent=2, ensure_ascii=False)[:3000])
except urllib.error.HTTPError as e:
    print('HTTP %d: %s' % (e.code, e.read().decode()[:500]))
except Exception as e:
    print('ERROR: %s' % e)
