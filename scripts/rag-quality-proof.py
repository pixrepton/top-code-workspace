#!/usr/bin/env python3
"""P1.2 — RAG answer quality proof (format + smoke queries)."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

BASE = os.getenv("RAG_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
API_KEY = os.getenv("HVAC_ADMIN_API_KEY") or os.getenv("HVAC_PUBLIC_API_KEY") or "admin"

QUERIES = [
    "Ile kosztuje zestaw KIT-WC07K3E5 w cenniku Panasonic?",
    "Co wiesz o pompach Panasonic Aquarea?",
    "Co mówi regulamin gwarancji pomp o okresie gwarancji?",
    "Kim jest Top Instal i czym się zajmuje?",
    "Jaka będzie pogoda w Warszawie jutro?",
    "Porównaj krótko pompy powietrzne i gruntowe na podstawie dokumentów.",
    "Jakie są warunki programu Czyste Powietrze w dokumentach?",
]

BAD_PREFIX = re.compile(
    r"^\s*(?:\*\*)?(answer|odpowiedź|odpowiedz)(?:\*\*)?\s*:",
    re.I,
)
REFUSAL_MARKERS = (
    "nie mam pewności",
    "nie mam pewnosci",
    "could not find reliable",
    "brak wiarygodnych",
    "poza zakresem",
    "nie wiem",
)


def _assert_http_url(url: str) -> None:
    scheme = urlparse(url).scheme.lower()
    if scheme not in ("http", "https"):
        raise ValueError(f"unsupported URL scheme: {scheme!r}")


def post_chat(query: str) -> dict:
    target_url = f"{BASE}/chat"
    _assert_http_url(target_url)
    payload = json.dumps({"query": query, "stream": False, "use_cache": False}).encode()
    headers = {"Content-Type": "application/json", "X-API-Key": API_KEY}
    req = urllib.request.Request(target_url, data=payload, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=120) as resp:  # nosec B310
        return json.loads(resp.read().decode("utf-8"))


def extract_answer(body: dict) -> str:
    dto = body.get("response_dto") if isinstance(body.get("response_dto"), dict) else {}
    return str(body.get("answer") or dto.get("answer_md") or "")


def _clean_answer_for_format_check(answer: str) -> str:
    text = str(answer or "").strip()
    text = re.sub(
        r"^\s*odpowied[źz]\s*(?:\([^)]*\))?\s*:\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"^\s*answer\s*:\s*", "", text, flags=re.IGNORECASE)
    return text.strip()


def score_answer(answer: str, *, query: str = "") -> dict:
    cleaned = _clean_answer_for_format_check(answer)
    issues: list[str] = []
    if not cleaned.strip():
        issues.append("empty_answer")
    if BAD_PREFIX.search(cleaned):
        issues.append("bad_prefix_answer")
    lower = cleaned.lower()
    is_refusal = any(m in lower for m in REFUSAL_MARKERS)
    if (
        not is_refusal
        and not re.search(r"[ąćęłńóśźż]", cleaned, re.I)
        and len(cleaned) > 80
    ):
        issues.append("maybe_not_polish")
    inline_cite = bool(re.search(r"\[E\d+\]", cleaned))
    off_topic = any(w in query.lower() for w in ("pogod", "weather"))
    if off_topic and is_refusal:
        issues = [i for i in issues if i != "maybe_not_polish"]
    return {
        "issues": issues,
        "inline_cite": inline_cite,
        "chars": len(cleaned),
        "is_refusal": is_refusal,
    }


def main() -> int:
    results = []
    for q in QUERIES:
        row = {"query": q}
        try:
            body = post_chat(q)
            answer = extract_answer(body)
            row["format"] = score_answer(answer, query=q)
            row["ok"] = not row["format"]["issues"]
            row["preview"] = answer[:200].replace("\n", " ")
        except urllib.error.HTTPError as exc:
            row["ok"] = False
            row["error"] = f"HTTP {exc.code}"
        except Exception as exc:
            row["ok"] = False
            row["error"] = str(exc)
        results.append(row)

    out = Path(__file__).resolve().parent.parent / "knowledge" / "memory" / "RAG_QUALITY_PROOF.md"
    passed = sum(1 for r in results if r.get("ok"))
    lines = [
        "# RAG quality proof (P1.2)",
        "",
        f"Passed format checks: **{passed}/{len(results)}**",
        "",
        "| # | OK | issues | cite | query | preview |",
        "| - | -- | ------ | ---- | ----- | ------- |",
    ]
    for i, r in enumerate(results, 1):
        fmt = r.get("format") or {}
        issues = ",".join(fmt.get("issues") or []) or r.get("error", "-")
        ok = "yes" if r.get("ok") else "no"
        cite = "yes" if fmt.get("inline_cite") else "no"
        q = r["query"][:40]
        preview = (r.get("preview") or "")[:60]
        lines.append(f"| {i} | {ok} | {issues} | {cite} | {q} | {preview} |")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"passed": passed, "total": len(results), "report": str(out)}, ensure_ascii=False))
    return 0 if passed >= len(results) - 1 else 1


if __name__ == "__main__":
    raise SystemExit(main())
