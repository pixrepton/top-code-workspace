#!/usr/bin/env python3
"""Read-only Sourcebot local health/search proof."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from http.client import RemoteDisconnected
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_ROOT = ROOT / ".artifacts" / "tooling-optimization"


def request_http(method: str, url: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    token = os.environ.get("SOURCEBOT_API_KEY")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=20) as resp:  # noqa: S310 - local operator URL by default
            body = resp.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(body) if body else None
            except json.JSONDecodeError:
                parsed = None
            return {
                "status": resp.status,
                "ok": 200 <= resp.status < 300,
                "json": parsed,
                "body_prefix": body[:500] if parsed is None else "",
            }
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {"status": exc.code, "ok": False, "body": body[:2000]}
    except (RemoteDisconnected, TimeoutError, URLError) as exc:
        return {"status": 0, "ok": False, "error": str(exc)}


def search(base_url: str, query: str) -> dict[str, Any]:
    payload = {
        "query": query,
        "matches": 20,
        "contextLines": 2,
        "whole": False,
        "isRegexEnabled": False,
        "isCaseSensitivityEnabled": True,
    }
    return request_http("POST", f"{base_url}/api/search", payload)


def summarize_search(result: dict[str, Any]) -> dict[str, Any]:
    body = result.get("json") if result.get("ok") else None
    files = body.get("files", []) if isinstance(body, dict) else []
    repos = sorted({str(item.get("repository")) for item in files if item.get("repository")})
    return {
        "status": result.get("status"),
        "ok": bool(result.get("ok")),
        "file_count": len(files),
        "repositories": repos[:10],
        "auth_required": result.get("status") in {401, 403},
    }


def wait_for_health(base_url: str, timeout: float) -> dict[str, Any]:
    deadline = time.time() + timeout
    last: dict[str, Any] = {}
    while time.time() < deadline:
        last = request_http("GET", f"{base_url}/api/health")
        if last.get("ok"):
            return last
        time.sleep(2)
    return last


def write_artifact(payload: dict[str, Any]) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = ARTIFACT_ROOT / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "sourcebot-proof.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:3000")
    parser.add_argument("--wait", type=float, default=5.0)
    parser.add_argument("--write-artifact", action="store_true")
    parser.add_argument("--allow-auth-required", action="store_true")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    health = wait_for_health(base_url, args.wait)
    web = request_http("GET", f"{base_url}/") if health.get("ok") else {}
    queries = {
        "CaseContextPack": search(base_url, "CaseContextPack") if health.get("ok") else {},
        "OfferDTO": search(base_url, "OfferDTO") if health.get("ok") else {},
    }
    searches = {name: summarize_search(result) for name, result in queries.items()}
    auth_required = bool(searches) and all(item.get("auth_required") for item in searches.values())
    payload = {
        "schema": "aios.tooling.sourcebot-proof.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "base_url": args.base_url,
        "health": health,
        "web_ui": {
            "status": web.get("status"),
            "ok": bool(web.get("ok")),
            "has_html": "<!DOCTYPE html>" in str(web.get("body_prefix", "")),
        },
        "searches": searches,
        "summary": {
            "health": "HEALTH_OK" if health.get("ok") else "HEALTH_FAIL",
            "web_ui": "WEB_UI_OK" if web.get("ok") else "WEB_UI_FAIL",
            "search": "SEARCH_AUTH_REQUIRED" if auth_required else "SEARCH_CHECKED",
        },
        "evidence_model": {
            "sourcebot_is_structural_search": True,
            "sourcebot_mcp_registered": False,
            "runtime_truth": False,
        },
    }
    if args.write_artifact:
        payload["artifact"] = str(write_artifact(payload))
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    all_searches_ok = all(item.get("ok") and item.get("file_count", 0) > 0 for item in payload["searches"].values())
    deploy_ok = bool(health.get("ok") and web.get("ok"))
    accepted_auth_boundary = bool(args.allow_auth_required and auth_required)
    return 0 if deploy_ok and (all_searches_ok or accepted_auth_boundary) else 1


if __name__ == "__main__":
    raise SystemExit(main())
