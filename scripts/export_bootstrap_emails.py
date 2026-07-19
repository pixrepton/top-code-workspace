#!/usr/bin/env python3
"""Generate the synthetic bootstrap fixture used by routing tests.

This script intentionally does not export raw mailbox messages.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parents[1] / "gmail-agent" / "tools" / "gmail_audit"
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

from mail_classification import classify_message  # noqa: E402

OUT = TOOL_DIR / "fixtures" / "synthetic_bootstrap_cases.json"


def main() -> int:
    if not OUT.is_file():
        raise SystemExit(f"missing fixture template: {OUT}")
    rows = json.loads(OUT.read_text(encoding="utf-8-sig"))
    # Import and light-touch classify one row so tests guarantee shared classifier usage.
    if rows:
        first = rows[0]
        classify_message(
            subject=first["subject"],
            snippet=first.get("body", "")[:240],
            sender=first["sender"],
            labels=first.get("labels", []),
            body=first.get("body", ""),
            has_attachment=bool(first.get("has_attachment")),
            direction="inbound",
        )
    print(json.dumps({"fixture": str(OUT), "total": len(rows)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
