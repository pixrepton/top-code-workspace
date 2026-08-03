#!/usr/bin/env python3
"""Emit kalk-top service_heartbeat to Node B (P3.11)."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlparse


def _env(name: str, default: str = "") -> str:
    return str(os.getenv(name, default) or "").strip()


def _assert_http_url(url: str) -> None:
    scheme = urlparse(url).scheme.lower()
    if scheme not in ("http", "https"):
        raise ValueError(f"unsupported URL scheme: {scheme!r}")


def main() -> int:
    base = _env("NODE_B_REGISTRY_BASE_URL", "http://127.0.0.1:8766").rstrip("/")
    token = _env("NODE_B_REGISTRY_TOKEN") or _env("TOPINSTAL_NODE_B_REGISTRY_TOKEN")
    if not token:
        print("WARN: NODE_B_REGISTRY_TOKEN not set — heartbeat skipped", file=sys.stderr)
        return 0

    body = {
        "event_type": "service_heartbeat",
        "source_repo": "kalk-top",
        "engagement_id": "",
        "payload": {
            "schema_version": "topinstal.os_event.v1",
            "summary_pl": "kalk-top lokalny heartbeat",
            "status": "ok",
            "emitted_at": datetime.now(timezone.utc).isoformat(),
        },
        "correlation": {},
    }
    target_url = f"{base}/internal/os-events"
    _assert_http_url(target_url)
    req = urllib.request.Request(
        target_url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:  # nosec B310
            raw = resp.read().decode("utf-8", errors="replace")
        print("heartbeat_ok", resp.status, raw[:200])
        return 0
    except urllib.error.HTTPError as exc:
        print(f"heartbeat_failed HTTP {exc.code}: {exc.read().decode()[:300]}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
