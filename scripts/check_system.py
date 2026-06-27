"""Check system state for the final report."""
import urllib.request
import json

token = 'local_ewXAeqaz0Dm6NifKXnQiWV94vGhAcWQAxpRj6t-YaBA'
base = 'http://localhost:8766'

# 1. System health status
print('=== 1. SYSTEM HEALTH STATUS ===')
req = urllib.request.Request('%s/system/health/status' % base)
try:
    resp = urllib.request.urlopen(req, timeout=10)
    data = json.loads(resp.read())
    print(json.dumps(data, indent=2, ensure_ascii=False)[:3000])
except urllib.error.HTTPError as e:
    body = e.read().decode()[:1000]
    print('HTTP %d: %s' % (e.code, body))
except Exception as e:
    print('ERROR: %s' % e)

# 2. Recent OS events
print('\n=== 2. RECENT OS EVENTS ===')
try:
    resp = urllib.request.urlopen('%s/system/os-events/recent?limit=10' % base, timeout=10)
    data = json.loads(resp.read())
    print(json.dumps(data, indent=2, ensure_ascii=False)[:2000])
except Exception as e:
    print('ERROR: %s' % e)

# 3. Gmail agent health
print('\n=== 3. GMAIL AGENT HEALTH ===')
try:
    resp = urllib.request.urlopen('%s/health' % base, timeout=10)
    print(json.dumps(json.loads(resp.read()), indent=2, ensure_ascii=False))
except Exception as e:
    print('ERROR: %s' % e)

# 4. RAG Health
print('\n=== 4. RAG HEALTH ===')
try:
    resp = urllib.request.urlopen('http://localhost:8000/health', timeout=10)
    print(json.dumps(json.loads(resp.read()), indent=2, ensure_ascii=False))
except Exception as e:
    print('ERROR: %s' % e)
