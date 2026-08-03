#!/usr/bin/env python3
"""Delete Gate B / proof mailbox cases that generate RISK:STALE noise (P1.3)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

GMAIL_AUDIT = Path(__file__).resolve().parent.parent / "gmail-agent" / "tools" / "gmail_audit"
if str(GMAIL_AUDIT) not in sys.path:
    sys.path.insert(0, str(GMAIL_AUDIT))

PROOF_PREFIXES = (
    "case_full_chain_proof_%",
    "case_similar_cases_v1_proof_%",
    "case_similar_cases_precedent_proof_%",
    "case_drive_agent_live_%",
)

TABLES_BY_CASE_ID = (
    "mailbox_memory_messages",
    "mailbox_memory_facts",
    "mailbox_memory_documents",
    "mailbox_memory_events",
    "operator_engagement_snapshots",
    "mailbox_memory_cases",
)


def _delete_by_case_ids(cur, case_ids: list[str], report: dict[str, int], prefix: str) -> None:
    if not case_ids:
        return
    from psycopg import sql

    print(f"Deleting {len(case_ids)} case(s) [{prefix}]...")
    for table in TABLES_BY_CASE_ID:
        if table == "mailbox_memory_cases":
            continue
        cur.execute(
            sql.SQL("DELETE FROM {} WHERE case_id = ANY(%s)").format(sql.Identifier(table)),
            (case_ids,),
        )
        report[f"{prefix}:{table}"] = cur.rowcount
    cur.execute("DELETE FROM mailbox_memory_cases WHERE case_id = ANY(%s)", (case_ids,))
    report[f"{prefix}:mailbox_memory_cases"] = cur.rowcount


def _delete_stale_dev_cases(cur, report: dict[str, int]) -> list[str]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    cur.execute(
        """
        SELECT case_id FROM mailbox_memory_cases
        WHERE updated_at IS NOT NULL AND updated_at < %s
          AND case_id NOT LIKE 'task_%%'
          AND case_id <> '_operator_desk'
        ORDER BY 1
        """,
        (cutoff,),
    )
    stale_ids = [row[0] for row in cur.fetchall()]
    _delete_by_case_ids(cur, stale_ids, report, "delete_stale")
    return stale_ids


def main() -> int:
    from config import load_settings

    settings = load_settings(require_groq=False, require_google=False)
    db_url = str(getattr(settings, "mailbox_memory_database_url", "") or "").strip()
    if not db_url:
        print("ERROR: MAILBOX_MEMORY_DATABASE_URL not configured", file=sys.stderr)
        return 1

    import psycopg
    from psycopg import sql

    report: dict[str, int] = {}
    deleted_case_ids: list[str] = []

    with psycopg.connect(db_url, connect_timeout=30) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT case_id FROM mailbox_memory_cases WHERE case_id LIKE ANY(%s) ORDER BY 1",
                (list(PROOF_PREFIXES),),
            )
            proof_ids = [row[0] for row in cur.fetchall()]
            if proof_ids:
                _delete_by_case_ids(cur, proof_ids, report, "delete_proof")
                deleted_case_ids.extend(proof_ids)

                cur.execute(
                    """
                    DELETE FROM agent_runtime_turns
                    WHERE engagement_id IN (
                        SELECT engagement_id FROM operator_engagement_snapshots
                        WHERE case_id LIKE ANY(%s)
                    )
                    """,
                    (list(PROOF_PREFIXES),),
                )
                report["delete_proof:agent_runtime_turns"] = cur.rowcount

            stale_ids = _delete_stale_dev_cases(cur, report)
            deleted_case_ids.extend(stale_ids)

        conn.commit()

    from event_spine.health_monitor import evaluate_deterministic_risk_flags

    class _Store:
        def __init__(self, url: str) -> None:
            self._url = url

        def fetch_cases(self, *, limit: int = 200):
            with psycopg.connect(self._url, connect_timeout=15) as conn, conn.cursor() as cur:
                cur.execute(
                    """
                        SELECT case_id, updated_at
                        FROM mailbox_memory_cases
                        ORDER BY updated_at DESC NULLS LAST
                        LIMIT %s
                        """,
                    (limit,),
                )
                return [
                    {
                        "case_id": case_id,
                        "updated_at": updated_at.isoformat() if updated_at else "",
                    }
                    for case_id, updated_at in cur.fetchall()
                ]

    flags = evaluate_deterministic_risk_flags(mailbox_store=_Store(db_url), engagement_snapshots=[])
    stale_left = [f for f in flags if f.get("risk") == "RISK:STALE"]

    summary = {
        "deleted_total": len(deleted_case_ids),
        "cleanup_report": report,
        "risk_flags_remaining": len(flags),
        "stale_remaining": len(stale_left),
        "stale_case_ids_remaining": [f.get("case_id") for f in stale_left],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
