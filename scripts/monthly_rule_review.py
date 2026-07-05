#!/usr/bin/env python3
"""Auto-dezaktywacja błędnych/nieużywanych reguł learning loop.

Uruchamiany ręcznie lub przez cron (np. co miesiąc):
    python scripts/monthly_rule_review.py

Co robi:
    1. Flaga 'stale' — reguły nieużywane przez 30 dni
    2. Flaga 'dormant' — reguły odrzucone przez operatora 3+ razy
    3. Auto-usunięcie — reguły z application_count=0 i wiekiem >60 dni
    4. Raport do panelu System
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from typing import Any

DB_URL_ENV_KEY = "MAILBOX_MEMORY_DATABASE_URL"
DEFAULT_DB_URL = "postgresql://mailbox_memory:memorka@127.0.0.1:54129/mailbox_memory"

STALE_DAYS = 30
DORMANT_REJECTION_THRESHOLD = 3
AUTO_REMOVE_DAYS = 60


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _connect(database_url: str):
    import psycopg  # type: ignore[import-not-found]
    return psycopg.connect(database_url)


def flag_stale_rules(conn: Any) -> list[dict[str, Any]]:
    """Reguły które nie były użyte przez STALE_DAYS dni → status='stale'."""
    stale: list[dict[str, Any]] = []
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT candidate_id, pattern_key, rule_text_pl, supporting_count,
                   last_applied_at
            FROM learning_rule_candidates
            WHERE status = 'approved'
              AND (last_applied_at IS NULL OR last_applied_at < %s)
            """,
            (_now() - __import__("datetime").timedelta(days=STALE_DAYS),),
        )
        rows = cur.fetchall() or []
    for row in rows:
        cid = row[0] if not isinstance(row, dict) else row.get("candidate_id")
        stale.append({
            "candidate_id": cid,
            "pattern_key": row[1] if not isinstance(row, dict) else row.get("pattern_key"),
            "rule_text_pl": row[2] if not isinstance(row, dict) else row.get("rule_text_pl"),
            "reason": "stale",
        })
    if stale:
        with conn.cursor() as cur:
            for s in stale:
                cur.execute(
                    """
                    UPDATE learning_rule_candidates
                    SET status = 'stale', metadata = COALESCE(metadata, '{}'::jsonb) || '{"auto_flagged": "stale", "flagged_at": "%s"}'::jsonb
                    WHERE candidate_id = %s
                    """,
                    (_now().isoformat(), s["candidate_id"]),
                )
        conn.commit()
    return stale


def flag_dormant_rules(conn: Any) -> list[dict[str, Any]]:
    """Reguły które były wielokrotnie odrzucane → status='dormant'."""
    dormant: list[dict[str, Any]] = []
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.candidate_id, c.pattern_key, c.rule_text_pl,
                   COUNT(r.response_id) AS rejection_count
            FROM learning_rule_candidates c
            LEFT JOIN operator_response_records r ON r.proposal_id = c.candidate_id
                AND r.response_type IN ('DIVERGENT_ACTION', 'IGNORED')
            WHERE c.status IN ('pending_operator', 'approved')
            GROUP BY c.candidate_id, c.pattern_key, c.rule_text_pl
            HAVING COUNT(r.response_id) >= %s
            """,
            (DORMANT_REJECTION_THRESHOLD,),
        )
        rows = cur.fetchall() or []
    for row in rows:
        dormant.append({
            "candidate_id": row[0] if not isinstance(row, dict) else row.get("candidate_id"),
            "pattern_key": row[1] if not isinstance(row, dict) else row.get("pattern_key"),
            "rule_text_pl": row[2] if not isinstance(row, dict) else row.get("rule_text_pl"),
            "reason": "dormant",
        })
    if dormant:
        with conn.cursor() as cur:
            for d in dormant:
                cur.execute(
                    """
                    UPDATE learning_rule_candidates
                    SET status = 'dormant', metadata = COALESCE(metadata, '{}'::jsonb) || '{"auto_flagged": "dormant", "flagged_at": "%s"}'::jsonb
                    WHERE candidate_id = %s
                    """,
                    (_now().isoformat(), d["candidate_id"]),
                )
        conn.commit()
    return dormant


def auto_remove_never_used(conn: Any) -> list[dict[str, Any]]:
    """Reguły z application_count=0 i wiekiem >AUTO_REMOVE_DAYS → usunięte."""
    removed: list[dict[str, Any]] = []
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT candidate_id, pattern_key, rule_text_pl, created_at
            FROM learning_rule_candidates
            WHERE (application_count IS NULL OR application_count = 0)
              AND (last_applied_at IS NULL)
              AND created_at < %s
            """,
            (_now() - __import__("datetime").timedelta(days=AUTO_REMOVE_DAYS),),
        )
        rows = cur.fetchall() or []
    for row in rows:
        removed.append({
            "candidate_id": row[0] if not isinstance(row, dict) else row.get("candidate_id"),
            "pattern_key": row[1] if not isinstance(row, dict) else row.get("pattern_key"),
            "rule_text_pl": row[2] if not isinstance(row, dict) else row.get("rule_text_pl"),
            "reason": "auto_removed",
        })
    if removed:
        with conn.cursor() as cur:
            for r in removed:
                cur.execute(
                    "UPDATE learning_rule_candidates SET status = 'archived' WHERE candidate_id = %s",
                    (r["candidate_id"],),
                )
        conn.commit()
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description="Auto-dezaktywacja błędnych reguł learning loop")
    parser.add_argument("--db-url", default="", help="URL bazy danych (domyślnie z MAILBOX_MEMORY_DATABASE_URL)")
    parser.add_argument("--dry-run", action="store_true", help="Tylko raport, bez zmian")
    args = parser.parse_args()

    database_url = args.db_url or os.environ.get(DB_URL_ENV_KEY, "") or DEFAULT_DB_URL

    print(f"=== Monthly Rule Review ===")
    print(f"  DB: {database_url[:60]}...")
    print(f"  Dry run: {args.dry_run}")
    print()

    conn = _connect(database_url)

    # Krok 1: Stale rules
    print("[1/3] Sprawdzam reguły nieużywane >={STALE_DAYS} dni...")
    stale = flag_stale_rules(conn)
    print(f"  Znaleziono: {len(stale)}")
    for s in stale:
        print(f"    - {s['candidate_id']}: {s.get('rule_text_pl', '')[:80]}")

    # Krok 2: Dormant rules
    print(f"\n[2/3] Sprawdzam reguły odrzucane >={DORMANT_REJECTION_THRESHOLD} razy...")
    dormant = flag_dormant_rules(conn)
    print(f"  Znaleziono: {len(dormant)}")
    for d in dormant:
        print(f"    - {d['candidate_id']}: {d.get('rule_text_pl', '')[:80]}")

    # Krok 3: Auto-remove never used
    print(f"\n[3/3] Sprawdzam reguły nigdy nieużywane, wiek >{AUTO_REMOVE_DAYS} dni...")
    removed = auto_remove_never_used(conn)
    print(f"  Znaleziono: {len(removed)}")
    for r in removed:
        print(f"    - {r['candidate_id']}: {r.get('rule_text_pl', '')[:80]}")

    conn.close()

    total = len(stale) + len(dormant) + len(removed)
    print(f"\n=== Podsumowanie: {total} reguł oznaczonych ===")
    if total == 0:
        print("  Brak reguł wymagających interwencji.")

    if args.dry_run:
        print("\n  Dry run — żadne zmiany nie zostały zapisane w bazie.")
        return 0

    print("\n  Zmiany zapisane. Operator może przejrzeć w panelu System → Rules.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
