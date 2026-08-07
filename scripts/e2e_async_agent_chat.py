"""Gate B: async agent-chat E2E proof (POST 202 + worker + poll).

Requires live Docker stack: gmail-agent-nodeb-api :8766 and signal_worker.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
PASS = 0
FAIL = 0
STEPS: list[tuple[str, bool, str]] = []

NODE_B = "http://127.0.0.1:8766"
DASZEK = "http://127.0.0.1:8090"
TOKEN = "local_ewXAeqaz0Dm6NifKXnQiWV94vGhAcWQAxpRj6t-YaBA"
AUTH = {"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"}


def _assert_http_url(url: str) -> None:
    scheme = urlparse(url).scheme.lower()
    if scheme not in ("http", "https"):
        raise ValueError(f"unsupported URL scheme: {scheme!r}")


def safe_urlopen(url_or_req, timeout: int = 30):
    if isinstance(url_or_req, str):
        _assert_http_url(url_or_req)
    else:
        _assert_http_url(url_or_req.full_url)
    return urllib.request.urlopen(url_or_req, timeout=timeout)  # nosec B310


def step(name: str, fn) -> None:
    global PASS, FAIL
    try:
        ok = bool(fn())
        if ok:
            PASS += 1
            STEPS.append((name, True, "PASS"))
            print(f"  [PASS] {name}")
        else:
            FAIL += 1
            STEPS.append((name, False, "FAIL"))
            print(f"  [FAIL] {name}")
    except Exception as exc:
        FAIL += 1
        STEPS.append((name, False, f"EXCEPTION: {exc}"))
        print(f"  [FAIL] {name}: {exc}")
        print(traceback.format_exc()[:300])


def http_get(url: str, timeout: int = 30) -> dict:
    resp = safe_urlopen(url, timeout=timeout)
    return json.loads(resp.read())


def http_post(url: str, payload: dict, headers: dict | None = None, timeout: int = 60) -> tuple[int, dict]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers=headers or AUTH,
        method="POST",
    )
    try:
        resp = safe_urlopen(req, timeout=timeout)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body) if body else {}
        except json.JSONDecodeError:
            parsed = {"raw": body}
        return exc.code, parsed


def nudge_worker_chat_jobs(max_jobs: int = 3) -> dict:
    """Best-effort: process queued jobs when signal_worker iteration is long."""
    cmd = [
        "docker",
        "exec",
        "-w",
        "/app/tools/gmail_audit",
        "gmail-agent-vps-gmail-agent-worker-1",
        "python",
        "-c",
        (
            "from config import load_settings; "
            "from agent_runtime.agent_chat_worker import process_agent_chat_jobs_tick; "
            "s=load_settings(require_groq=False, require_google=False); "
            f"print(process_agent_chat_jobs_tick(s, max_jobs={max_jobs}))"
        ),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180, check=False)
        return {"ok": proc.returncode == 0, "stdout": proc.stdout.strip(), "stderr": proc.stderr[-500:]}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def poll_job(job_id: str, *, timeout_sec: int = 240) -> dict:
    deadline = time.monotonic() + timeout_sec
    last: dict = {}
    nudged = False
    while time.monotonic() < deadline:
        last = http_get(f"{NODE_B}/agent-chat/jobs/{job_id}", timeout=15)
        status = str(last.get("status") or "").lower()
        if status in {"completed", "failed", "hitl_required"}:
            return last
        if not nudged and (deadline - time.monotonic()) < (timeout_sec - 45):
            nudge_worker_chat_jobs(max_jobs=2)
            nudged = True
        time.sleep(3)
    if not nudged:
        nudge_worker_chat_jobs(max_jobs=2)
        for _ in range(20):
            last = http_get(f"{NODE_B}/agent-chat/jobs/{job_id}", timeout=15)
            status = str(last.get("status") or "").lower()
            if status in {"completed", "failed", "hitl_required"}:
                return last
            time.sleep(3)
    return last


print("=" * 60)
print("GATE B — ASYNC AGENT CHAT E2E")
print("=" * 60)

step("gmail-agent /health", lambda: http_get(f"{NODE_B}/health").get("ok") is True)

async_status = {}
async_body: dict = {}


def _enqueue_async() -> bool:
    status, body = http_post(
        f"{NODE_B}/agent-chat/async",
        {
            "user_input": "Gate B async proof: podsumuj stan pipeline w 1 zdaniu.",
            "session_id": f"gateb_async_{int(time.time())}",
        },
        timeout=30,
    )
    async_status["code"] = status
    async_body.update(body if isinstance(body, dict) else {})
    return status == 202 and bool(body.get("job_id")) and bool(body.get("command_id"))


step("POST /agent-chat/async returns 202 + job_id", _enqueue_async)

job_id = str(async_body.get("job_id") or "")
command_id = str(async_body.get("command_id") or "")

job_result: dict = {}


def _poll_or_fail() -> bool:
    if not job_id:
        return False
    job_result.update(poll_job(job_id, timeout_sec=180))
    status = str(job_result.get("status") or "").lower()
    receipt = job_result.get("receipt") if isinstance(job_result.get("receipt"), dict) else {}
    return status in {"completed", "hitl_required"} and str(receipt.get("command_id") or "") == command_id


step("GET /agent-chat/jobs/{id} completes with matching receipt", _poll_or_fail)

receipt = job_result.get("receipt") if isinstance(job_result.get("receipt"), dict) else {}
step(
    "receipt has operator_command spine fields",
    lambda: receipt.get("receipt_kind") == "operator_command"
    and bool(receipt.get("signal_id"))
    and receipt.get("status") in {"completed", "hitl_required"},
)

# Daszek proxy path — routes require WP auth; verify Node B bridge from WP container.
daszek_bridge: dict = {}


def _daszek_node_b_bridge_async() -> bool:
    script = r"""
require '/var/www/html/wp-load.php';
if (!function_exists('daszek_node_b_get_json')) {
    echo json_encode(['ok' => false, 'error' => 'daszek_node_b_get_json missing']);
    exit(0);
}
$body = [
    'user_input' => 'Gate B Daszek bridge async ping.',
    'session_id' => 'gateb_daszek_bridge_' . time(),
];
$result = daszek_node_b_get_json('/agent-chat/async', 'POST', $body);
if (is_wp_error($result)) {
    echo json_encode(['ok' => false, 'error' => $result->get_error_message()]);
    exit(0);
}
echo json_encode(['ok' => true, 'result' => $result], JSON_UNESCAPED_UNICODE);
"""
    cmd = ["docker", "exec", "daszek-local-wordpress", "php", "-r", script]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
    daszek_bridge["stdout"] = proc.stdout.strip()
    daszek_bridge["stderr"] = proc.stderr[-300:]
    try:
        payload = json.loads(proc.stdout.strip() or "{}")
    except json.JSONDecodeError:
        return False
    daszek_bridge["payload"] = payload
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    return bool(payload.get("ok")) and bool(result.get("job_id"))


step("Daszek WP bridge POST /agent-chat/async via daszek_node_b_get_json", _daszek_node_b_bridge_async)

if daszek_bridge.get("payload", {}).get("result", {}).get("job_id"):
    bridge_job = str(daszek_bridge["payload"]["result"]["job_id"])

    def _daszek_bridge_poll() -> bool:
        polled = poll_job(bridge_job, timeout_sec=180)
        status = str(polled.get("status") or "").lower()
        return status in {"completed", "hitl_required"}

    step("Daszek-enqueued job completes on Node B poll API", _daszek_bridge_poll)

print("\n" + "=" * 60)
print(f"RESULTS: {PASS} PASS, {FAIL} FAIL")
print("=" * 60)
for name, ok, detail in STEPS:
    print(f"  [{detail[:4]}] {name}")

if FAIL > 0:
    sys.exit(1)
print("\nGATE B ASYNC E2E: PASS")
sys.exit(0)
