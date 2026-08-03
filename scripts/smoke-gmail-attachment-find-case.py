#!/usr/bin/env python3
"""Find a mailbox_memory_attachments row suitable for attachment download smoke."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "gmail-agent" / "tools" / "gmail_audit"
sys.path.insert(0, str(TOOL))

from config import load_settings  # noqa: E402
from mailbox_memory_store import PostgresMailboxMemoryStore  # noqa: E402


def main() -> int:
    settings = load_settings(require_groq=False, require_google=False)
    db_url = str(settings.mailbox_memory_database_url or "").strip()
    if not db_url:
        print(json.dumps({"error": "MAILBOX_MEMORY_DATABASE_URL not configured"}))
        return 2
    store = PostgresMailboxMemoryStore(db_url)
    row = store._fetch_one(
        """
        SELECT case_id, attachment_id, file_name, mime_type, blob_path,
               gmail_attachment_id, message_id
        FROM mailbox_memory_attachments
        WHERE (
            (blob_path IS NOT NULL AND blob_path <> '')
            OR (
                gmail_attachment_id IS NOT NULL AND gmail_attachment_id <> ''
                AND message_id IS NOT NULL AND message_id <> ''
            )
        )
        ORDER BY
            CASE WHEN blob_path IS NOT NULL AND blob_path <> '' THEN 0 ELSE 1 END,
            updated_at DESC NULLS LAST,
            created_at DESC NULLS LAST
        LIMIT 1
        """,
        {},
    )
    if not row:
        print(json.dumps({"error": "no attachment row with blob_path or gmail ids"}))
        return 2
    print(
        json.dumps(
            {
                "case_id": row["case_id"],
                "attachment_ref": row["attachment_id"],
                "file_name": row.get("file_name"),
                "blob_path": row.get("blob_path"),
                "has_gmail": bool(row.get("gmail_attachment_id")),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
