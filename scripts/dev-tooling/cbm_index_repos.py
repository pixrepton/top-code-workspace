#!/usr/bin/env python3
"""Call CBM index_repository via stdio MCP."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cbm_index_core import (  # noqa: E402
    NESTED_REPOS,
    index_repo,
    index_target,
    resolve_targets,
)
from cbm_mcp_stdio import CBM_ENV, ROOT  # noqa: E402

__all__ = ["CBM_ENV", "NESTED_REPOS", "ROOT", "index_repo", "main"]

WORKSPACE = Path(r"C:/Users/compg/Desktop/top-code workspace")


def main() -> int:
    only = {item.strip() for item in sys.argv[1:] if item.strip()}
    results: list[dict[str, Any]] = []
    failures = 0
    for label, path in resolve_targets(WORKSPACE, only):
        entry, failed = index_target(label, path)
        results.append(entry)
        failures += int(failed)
    print(json.dumps({"failures": failures, "results": results}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
