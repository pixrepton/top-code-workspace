"""Check gmail-agent cases database and endpoints."""
import urllib.request
import json

token = 'local_ewXAeqaz0Dm6NifKXnQiWV94vGhAcWQAxpRj6t-YaBA'
base = 'http://localhost:8766'

# Check /cases?limit=5&status=active
print('=== CASES LIST ===')
req = urllib.request.Request('%s/cases?limit=5&status=active' % base, headers={
    'Authorization': 'Bearer %s' % token
})
try:
    resp = urllib.request.urlopen(req, timeout=10)
    data = json.loads(resp.read())
    print(json.dumps(data, indent=2, ensure_ascii=False)[:2000])
except urllib.error.HTTPError as e:
    print('HTTP %d: %s' % (e.code, e.read().decode()[:1000]))
except Exception as e:
    print('ERROR: %s' % e)

# Try /cases without limit
print('\n=== CASES (no filter) ===')
req = urllib.request.Request('%s/cases' % base, headers={
    'Authorization': 'Bearer %s' % token
})
try:
    resp = urllib.request.urlopen(req, timeout=10)
    data = json.loads(resp.read())
    print(json.dumps(data, indent=2, ensure_ascii=False)[:2000])
except urllib.error.HTTPError as e:
    print('HTTP %d: %s' % (e.code, e.read().decode()[:1000]))
except Exception as e:
    print('ERROR: %s' % e)

# Check os-events (the one we injected)
print('\n=== RECENT OS EVENTS ===')
try:
    resp = urllib.request.urlopen('%s/system/os-events/recent?limit=5' % base, timeout=10)
    data = json.loads(resp.read())
    print(json.dumps(data, indent=2, ensure_ascii=False)[:2000])
except urllib.error.HTTPError as e:
    print('HTTP %d: %s' % (e.code, e.read().decode()[:1000]))
except Exception as e:
    print('ERROR: %s' % e)
