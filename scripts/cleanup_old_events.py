#!/usr/bin/env python3
"""Usuwa stare eventy z unified_os_events (TTL 90 dni)."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

import psycopg


def cleanup_events(db_url: str, ttl_days: int = 90, dry_run: bool = False) -> int:
    """Usuwa eventy starsze niż N dni. Zwraca liczbę usuniętych (lub do usunięcia przy dry_run)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=ttl_days)
    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        if dry_run:
            cur.execute("SELECT COUNT(*) FROM unified_os_events WHERE created_at < %s", (cutoff,))
            return cur.fetchone()[0]
        cur.execute("DELETE FROM unified_os_events WHERE created_at < %s", (cutoff,))
        return cur.rowcount


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cleanup starych eventów z unified_os_events")
    parser.add_argument("--db-url", required=True, help="Postgres URL do mailbox_memory")
    parser.add_argument("--ttl-days", type=int, default=90, help="Eventy starsze niż N dni (domyślnie 90)")
    parser.add_argument("--dry-run", action="store_true", help="Tylko policz, nie usuwaj")
    args = parser.parse_args()
    count = cleanup_events(args.db_url, args.ttl_days, args.dry_run)
    suffix = "" if count == 1 else "ów" if count in (2, 3, 4) else "ów"
    print(f"{'DRY RUN: ' if args.dry_run else ''}Usunięto {count} event{suffix}")
