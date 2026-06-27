"""Execute SCENARIO 1 — new cold lead."""
import urllib.request, json, sys

token = 'local_ewXAeqaz0Dm6NifKXnQiWV94vGhAcWQAxpRj6t-YaBA'
base = 'http://localhost:8766'

# Step 1: Send the lead via /agent-chat
payload = {
    "user_input": (
        "Nowy lead od klienta: Marek Wisniewski (marek.wisniewski@gmail.com, tel: 507-123-456) "
        "zainteresowany montazem pompy ciepla powietrze-woda w domu jednorodzinnym 180m2, "
        "budynek z 2005 roku, ogrzewanie dotychczas gazowe (kociol Viessmann 24kW). "
        "Klient pytal o dofinansowanie z Czystego Powietrza. "
        "Prosze o utworzenie sprawy i przygotowanie draft odpowiedzi z informacja o dofinansowaniu."
    ),
    "session_id": "scenario1_lead_marek",
    "case_id": ""
}

print("=== STEP 1: Sending lead via /agent-chat ===")
req = urllib.request.Request(
    '%s/agent-chat' % base,
    data=json.dumps(payload).encode(),
    headers={'Content-Type': 'application/json', 'Authorization': 'Bearer %s' % token},
    method='POST'
)
try:
    resp = urllib.request.urlopen(req, timeout=180)
    data = json.loads(resp.read())
    print(json.dumps(data, indent=2, ensure_ascii=False))
    
    # Save to file
    with open('scripts/proof/03-scenario1-response.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    signal_id = data.get('signal_id', '')
    engagement_id = data.get('engagement_id', '')
    
except urllib.error.HTTPError as e:
    body = e.read().decode()
    print('HTTP %d: %s' % (e.code, body[:2000]))
    signal_id = ''
    engagement_id = ''
except Exception as e:
    print('ERROR: %s' % e)
    signal_id = ''
    engagement_id = ''

# Step 2: Check OS events
print("\n\n=== STEP 2: Checking OS events ===")
try:
    req = urllib.request.Request('%s/system/os-events/recent?limit=5' % base)
    resp = urllib.request.urlopen(req, timeout=10)
    events = json.loads(resp.read())
    print(json.dumps(events, indent=2, ensure_ascii=False)[:2000])
    with open('scripts/proof/04-scenario1-os-events.json', 'w', encoding='utf-8') as f:
        json.dump(events, f, indent=2, ensure_ascii=False)
except Exception as e:
    print('ERROR: %s' % e)

# Step 3: Check health endpoints
print("\n\n=== STEP 3: Health checks ===")
health_results = {}

# /health (gmail-agent)
try:
    resp = urllib.request.urlopen('%s/health' % base, timeout=10)
    health_results['gmail_health'] = json.loads(resp.read())
except Exception as e:
    health_results['gmail_health'] = {'error': str(e)}

# /health (RAG)
try:
    resp = urllib.request.urlopen('http://localhost:8000/health', timeout=10)
    health_results['rag_health'] = json.loads(resp.read())
except Exception as e:
    health_results['rag_health'] = {'error': str(e)}

# /system/health/status
try:
    req = urllib.request.Request('%s/system/health/status' % base)
    resp = urllib.request.urlopen(req, timeout=10)
    health_results['system_health'] = json.loads(resp.read())
except Exception as e:
    health_results['system_health'] = {'error': str(e)}

print(json.dumps(health_results, indent=2, ensure_ascii=False))
with open('scripts/proof/07-health-endpoints.json', 'w', encoding='utf-8') as f:
    json.dump(health_results, f, indent=2, ensure_ascii=False)

# Summary
print("\n\n=== SCENARIO 1 SUMMARY ===")
print("Signal ID: %s" % signal_id)
print("Engagement ID: %s" % engagement_id)
print("Proposals created: %s" % ('YES' if signal_id else 'NO'))
print("Proof pack saved to: scripts/proof/")
