#!/usr/bin/env python3
"""P1.3 — deterministic risk flags report for operator decision."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

GMAIL_AUDIT = Path(__file__).resolve().parent.parent / "gmail-agent" / "tools" / "gmail_audit"
if str(GMAIL_AUDIT) not in sys.path:
    sys.path.insert(0, str(GMAIL_AUDIT))


def main() -> int:
    from config import load_settings
    from event_spine.health_monitor import evaluate_deterministic_risk_flags

    settings = load_settings(require_groq=False, require_google=False)
    db_url = str(getattr(settings, "mailbox_memory_database_url", "") or "").strip()
    if not db_url:
        print("ERROR: MAILBOX_MEMORY_DATABASE_URL not configured", file=sys.stderr)
        return 1

    import psycopg

    snapshots: list[dict] = []
    with psycopg.connect(db_url, connect_timeout=15) as conn, conn.cursor() as cur:
        cur.execute(
            """
                SELECT engagement_id, case_id, snapshot_data, updated_at
                FROM operator_engagement_snapshots
                ORDER BY updated_at DESC NULLS LAST
                LIMIT 500
                """
        )
        for eid, case_id, data, updated_at in cur.fetchall():
            snap = data if isinstance(data, dict) else {}
            if not isinstance(snap, dict):
                continue
            snap.setdefault("engagement_id", eid)
            snap.setdefault("case_id", case_id)
            if updated_at:
                snap.setdefault("updated_at", updated_at.isoformat())
            snapshots.append(snap)

    class _Store:
        def fetch_cases(self, *, limit: int = 200):
            with psycopg.connect(db_url, connect_timeout=15) as conn, conn.cursor() as cur:
                cur.execute(
                    """
                        SELECT case_id, updated_at
                        FROM mailbox_memory_cases
                        ORDER BY updated_at DESC NULLS LAST
                        LIMIT %s
                        """,
                    (limit,),
                )
                rows = []
                for case_id, updated_at in cur.fetchall():
                    rows.append(
                        {
                            "case_id": case_id,
                            "updated_at": updated_at.isoformat() if updated_at else "",
                        }
                    )
                return rows

    flags = evaluate_deterministic_risk_flags(
        mailbox_store=_Store(),
        engagement_snapshots=snapshots,
    )
    by_risk = Counter(str(f.get("risk") or "?") for f in flags)
    stale = [f for f in flags if f.get("risk") == "RISK:STALE"]
    blocked = [f for f in flags if f.get("risk") == "RISK:BLOCKED"]
    overdue = [f for f in flags if f.get("risk") == "RISK:OVERDUE"]

    out_path = Path(__file__).resolve().parent.parent / "knowledge" / "memory" / "RISK_FLAGS_REPORT.md"
    lines = [
        "# Risk flags report (P1.3)",
        "",
        f"Total flags: **{len(flags)}**",
        "",
        "## Summary by type",
        "",
        "| Risk | Count |",
        "| ---- | ----- |",
    ]
    for risk, count in sorted(by_risk.items()):
        lines.append(f"| {risk} | {count} |")
    lines.extend(
        [
            "",
            "## Operator options",
            "",
            "1. **leave** — flags inform observability only",
            "2. **auto-resolve** — mark stale cases completed/archived (script TBD per case_kind)",
            "3. **archive** — move to cold storage / suppress from feed",
            "",
            "## RISK:STALE (case no update >7d)",
            "",
        ]
    )
    for item in stale[:40]:
        lines.append(
            f"- `{item.get('case_id')}` — {item.get('days_since_update')}d — last `{item.get('last_update')}`"
        )
    if len(stale) > 40:
        lines.append(f"- … +{len(stale) - 40} more")
    lines.extend(["", "## RISK:BLOCKED (HITL >3d)", ""])
    for item in blocked[:20]:
        lines.append(
            f"- `{item.get('engagement_id')}` case `{item.get('case_id')}` — {item.get('days_pending')}d pending"
        )
    lines.extend(["", "## RISK:OVERDUE (SLA >48h)", ""])
    for item in overdue[:20]:
        lines.append(
            f"- `{item.get('engagement_id')}` case `{item.get('case_id')}` — {item.get('hours_elapsed')}h"
        )

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"total": len(flags), "by_risk": dict(by_risk), "report": str(out_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
