"""Test the exact extraction path the agent uses."""
import sys, os
sys.path.insert(0, '/app/tools/gmail_audit')

from config import load_settings
from intake_payload import coerce_source_snapshot
from signal_extractor import run_signal_extraction

s = load_settings(require_groq=False, require_google=False)

# Simulate what _run_llm_extraction does:
# signal_payload contains user_input, session_id, case_id
signal_payload = {
    "user_input": "Nowy lead: Marek Wisniewski, dom 180m2, pompa ciepla",
    "session_id": "test_session",
    "case_id": ""
}

text = signal_payload.get("user_input", "")

snap = coerce_source_snapshot({"source_message": {
    "subject": signal_payload.get("subject", ""),
    "body": signal_payload.get("body_text", "") or text,
    "snippet": signal_payload.get("snippet", ""),
    "from": signal_payload.get("customer_email", ""),
    "message_id": signal_payload.get("message_id", ""),
}})

res = run_signal_extraction(
    settings=s,
    snapshot=snap,
    context_bundle={"case_id": "test_case_001"},
)

import json
print("parse_status:", res.get("parse_status"))
print("error_reason:", res.get("error_reason", ""))
print("Result:", json.dumps(res, indent=2, ensure_ascii=False)[:1000])
