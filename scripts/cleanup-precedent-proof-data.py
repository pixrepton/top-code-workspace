#!/usr/bin/env python3
"""Remove stale precedent-proof test cases from mailbox memory (P1.3)."""

from __future__ import annotations

import sys
from pathlib import Path

GMAIL_AUDIT = Path(__file__).resolve().parent.parent / "gmail-agent" / "tools" / "gmail_audit"
if str(GMAIL_AUDIT) not in sys.path:
    sys.path.insert(0, str(GMAIL_AUDIT))

PREFIX = "case_similar_cases_precedent_proof_"


def main() -> int:
    from config import load_settings

    settings = load_settings(require_groq=False, require_google=False)
    db_url = str(getattr(settings, "mailbox_memory_database_url", "") or "").strip()
    if not db_url:
        print("ERROR: MAILBOX_MEMORY_DATABASE_URL not configured", file=sys.stderr)
        return 1

    import psycopg

    tables_case_id = (
        "mailbox_memory_messages",
        "mailbox_memory_facts",
        "mailbox_memory_documents",
        "mailbox_memory_events",
        "mailbox_memory_cases",
        "operator_engagement_snapshots",
    )

    report: dict[str, int] = {}
    with psycopg.connect(db_url, connect_timeout=15) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT case_id FROM mailbox_memory_cases WHERE case_id LIKE %s",
                (f"{PREFIX}%",),
            )
            case_ids = [row[0] for row in cur.fetchall()]
            if not case_ids:
                print(f"No rows matching {PREFIX}*")
                return 0

            print(f"Deleting {len(case_ids)} precedent-proof case(s)...")
            for table in tables_case_id:
                cur.execute(
                    f"DELETE FROM {table} WHERE case_id LIKE %s",
                    (f"{PREFIX}%",),
                )
                report[table] = cur.rowcount
        conn.commit()

    print("cleanup_report", report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
