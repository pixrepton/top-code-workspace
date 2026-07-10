#!/usr/bin/env python3
"""P2.6 — compare RAG config.py getenv keys vs .env.example."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "rag-chat-asystent" / "backend" / "config.py"
EXAMPLE = ROOT / "rag-chat-asystent" / ".env.example"
OUT = ROOT / "knowledge" / "memory" / "RAG_ENV_AUDIT.md"

DOC_ONLY_PREFIXES = (
    "CIEPLO_",
    "INGRESS_",
    "MAIL_",
    "WEB_VERIFY_",
)


def _config_keys() -> set[str]:
    text = CONFIG.read_text(encoding="utf-8")
    return set(re.findall(r'os\.getenv\("([A-Z0-9_]+)"', text))


def _example_keys() -> set[str]:
    keys: set[str] = set()
    for line in EXAMPLE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            keys.add(line.split("=", 1)[0].strip())
    return keys


def main() -> int:
    cfg = sorted(_config_keys())
    ex = _example_keys()
    missing = sorted(k for k in cfg if k not in ex)
    extra = sorted(k for k in ex if k not in cfg)
    active = [k for k in cfg if not any(k.startswith(p) for p in DOC_ONLY_PREFIXES)]

    lines = [
        "# RAG env audit (P2.6)",
        "",
        f"config.py keys: **{len(cfg)}** | .env.example keys: **{len(ex)}**",
        "",
        "## Missing from .env.example (in config.py)",
        "",
    ]
    if missing:
        for k in missing:
            tag = "DOC-ONLY?" if any(k.startswith(p) for p in DOC_ONLY_PREFIXES) else "ACTIVE"
            lines.append(f"- `{k}` ({tag})")
    else:
        lines.append("- (none)")
    lines.extend(["", "## In .env.example but not config.py", ""])
    if extra:
        for k in extra:
            lines.append(f"- `{k}`")
    else:
        lines.append("- (none)")
    lines.extend(
        [
            "",
            "## ACTIVE core (recommended in live .env)",
            "",
            "```",
            *active[:60],
            "```",
            "",
        ]
    )
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"audit_ok missing={len(missing)} extra={len(extra)} -> {OUT}")
    return 0 if len([k for k in missing if k in active]) < 5 else 1


if __name__ == "__main__":
    raise SystemExit(main())
