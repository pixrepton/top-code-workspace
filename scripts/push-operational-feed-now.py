#!/usr/bin/env python3
"""One-shot operational feed push to Daszek (runtime proof / recovery)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GMAIL_AUDIT = ROOT / "gmail-agent" / "tools" / "gmail_audit"
if str(GMAIL_AUDIT) not in sys.path:
    sys.path.insert(0, str(GMAIL_AUDIT))

from config import load_settings
from daszek_v3_feed_runtime import maybe_push_operational_feed_from_run_state
from gmail_intake import attach_daszek_client, attach_daszek_v2_manifest_from_settings, init_run_state
from mailbox_memory_runtime import build_mailbox_memory_runtime


def main() -> int:
    settings = load_settings(require_groq=False, require_google=False)
    runtime = build_mailbox_memory_runtime(settings)
    if runtime is None:
        print("ERROR: mailbox memory runtime unavailable", file=sys.stderr)
        return 1
    bootstrap = getattr(runtime, "bootstrap", None)
    if callable(bootstrap):
        bootstrap()

    run_state = init_run_state(
        run_id="push-operational-feed-now",
        run_dir=GMAIL_AUDIT / "runs" / "push-operational-feed-now",
        command="push-operational-feed-now",
        selector={"type": "manual_feed_push"},
        mailbox="signal-runtime",
        model=getattr(settings, "groq_model", ""),
        schema_path=None,
        source_run=None,
        push_daszek=True,
        runtime_controls={},
    )
    attach_daszek_v2_manifest_from_settings(run_state, settings)
    run_state["mailbox_memory_runtime"] = runtime
    attach_daszek_client(run_state, settings)

    maybe_push_operational_feed_from_run_state(
        run_state=run_state,
        settings=settings,
        trigger_message_id="manual-push-operational-feed-now",
    )
    # Feed push runs in a background thread pool; wait briefly for summary counters.
    time.sleep(5)

    summary = run_state.get("summary") or {}
    print(
        "push_submitted",
        {
            "push_count": summary.get("operational_feed_push_count"),
            "last_snapshot_id": summary.get("last_operational_feed_snapshot_id"),
            "failed": summary.get("operational_feed_push_failed"),
            "debounced": summary.get("operational_feed_push_debounced"),
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
