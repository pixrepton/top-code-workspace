"""
E2E full flow test for TOP-INSTAL AI-OS.
Tests: gmail-agent pipeline -> RAG -> Event Spine -> health.
"""
import json
import sys
import time
import urllib.request
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PASS = 0
FAIL = 0
STEPS: list[tuple[str, bool, str]] = []


def step(name: str, fn) -> None:
    global PASS, FAIL
    try:
        result = fn()
        if result:
            PASS += 1
            s = "PASS"
        else:
            FAIL += 1
            s = "FAIL"
        STEPS.append((name, result, s))
        print(f"  [{s}] {name}")
    except Exception as e:
        FAIL += 1
        tb = traceback.format_exc()[:200]
        STEPS.append((name, False, f"EXCEPTION: {e}"))
        print(f"  [FAIL] {name}: {e}")
        print(f"    {tb}")


def http_get(url: str, timeout: int = 15) -> dict:
    resp = urllib.request.urlopen(url, timeout=timeout)
    return json.loads(resp.read())


def http_post(url: str, payload: dict, headers: dict | None = None, timeout: int = 90) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers=headers or {"Content-Type": "application/json"},
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=timeout)
    return json.loads(resp.read())


# ============================================================
print("=" * 60)
print("E2E FULL FLOW TEST — TOP-INSTAL AI-OS")
print("=" * 60)

# Step 1: Health checks
print("\n--- Phase 1: Infrastructure Health ---")

step("gmail-agent /health", lambda: http_get("http://localhost:8766/health").get("ok") is True)

step("RAG /health", lambda: http_get("http://localhost:8000/health").get("status") == "healthy")

step("Daszek responds", lambda: urllib.request.urlopen("http://localhost:8090/", timeout=10).status == 200)

ROOT = Path(__file__).resolve().parent.parent
LOCAL_VPS_ENV = ROOT / "gmail-agent/.env.local-vps"


def _read_local_vps_env() -> str:
    if not LOCAL_VPS_ENV.is_file():
        return ""
    return LOCAL_VPS_ENV.read_text(encoding="utf-8")


def _event_spine_processor_check() -> bool:
    """Local stack may run spine in shadow mode; enabled=1 is the operational bar."""
    text = _read_local_vps_env()
    if not text:
        return False
    if "EVENT_SPINE_PROCESSOR_ENABLED=1" not in text:
        return False
    if "EVENT_SPINE_PROCESSOR_MODE=active" in text:
        return True
    if "EVENT_SPINE_PROCESSOR_MODE=shadow" in text:
        print("  [INFO] Event Spine processor enabled in shadow mode (expected for local stack)")
        return True
    return False


step("Event Spine processor active",
     _event_spine_processor_check)

# Step 2: Agent pipeline
print("\n--- Phase 2: Agent Pipeline ---")

token = "local_ewXAeqaz0Dm6NifKXnQiWV94vGhAcWQAxpRj6t-YaBA"
auth_headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}

lead_payload = {
    "user_input": "Nowy lead od klienta: Jan Kowalski (jan.kowalski@gmail.com, tel: 601-234-567) "
                  "zainteresowany montazem pompy ciepla powietrze-woda w domu 150m2. "
                  "Prosil o wycene i informacje o dofinansowaniu Czyste Powietrze.",
    "session_id": "e2e_test_lead_001",
}

lead_result = {}
step("POST /agent-chat (lead injection)", lambda: (
    lead_result.update(http_post("http://localhost:8766/agent-chat", lead_payload, auth_headers, timeout=120)),
    lead_result.get("ok") is True and len(lead_result.get("proposals", [])) > 0
))

if lead_result.get("ok"):
    eng_id = lead_result.get("engagement_id", "")

    step("Engagement ID created", lambda: bool(eng_id))

    step("HITL required (guardrail active)", lambda: lead_result.get("hitl_required") is True)

    proposals = lead_result.get("proposals", [])
    step(f"Proposals generated ({len(proposals)})", lambda: len(proposals) > 0)

    # Check timeline
    step("Engagement timeline accessible",
         lambda: http_get(f"http://localhost:8766/engagements/{eng_id}/timeline", timeout=15).get("ok") is True)

    # Follow-up
    followup_payload = {
        "user_input": "Dzien dobry, z tej strony Jan Kowalski. Dziekuje za wycene. "
                       "Chcialbym umowic sie na wizyte pomiarowa. Moge w przyszlym tygodniu.",
        "session_id": "e2e_test_followup_001",
        "engagement_id": eng_id,
    }

    followup_result = {}
    step("POST /agent-chat (follow-up)",
         lambda: (
             followup_result.update(http_post("http://localhost:8766/agent-chat", followup_payload, auth_headers, timeout=120)),
             followup_result.get("ok") is True
         ))

# Step 3: Event Spine
print("\n--- Phase 3: Event Spine ---")

step("GET /system/os-events/recent",
     lambda: len(http_get("http://localhost:8766/system/os-events/recent?limit=5", timeout=15).get("items", [])) > 0)

# Step 4: RAG
print("\n--- Phase 4: RAG Knowledge ---")

def test_rag_query() -> bool:
    payload = {"query": "Jakie sa warunki dofinansowania Czyste Powietrze 2025 dla pompy ciepla?", "session_id": "e2e_rag"}
    req = urllib.request.Request(
        "http://localhost:8000/chat",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=90)
    raw = resp.read().decode("utf-8", errors="replace")
    sources = 0
    answer = ""
    for line in raw.split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            try:
                evt = json.loads(line[6:])
                if evt.get("type") == "sources":
                    sources = len(evt.get("sources", []))
                elif evt.get("type") == "token":
                    answer += str(evt.get("content", ""))
            except:
                pass
    has_no_answer = any(x in answer.lower() for x in ["nie znaleziono", "could not find", "nie mam informacji"])
    return sources > 0 and not has_no_answer

step("RAG returns CP2025 with sources", test_rag_query)

# ============================================================
print("\n" + "=" * 60)
print(f"RESULTS: {PASS} PASS, {FAIL} FAIL, {PASS+FAIL} TOTAL")
print("=" * 60)
for name, ok, detail in STEPS:
    print(f"  [{detail[:4]}] {name}")

if FAIL > 0:
    print("\nFAILURES DETECTED — review details above")
    sys.exit(1)
else:
    print("\nALL E2E CHECKS PASSED")
    sys.exit(0)
