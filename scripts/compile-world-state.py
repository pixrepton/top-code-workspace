#!/usr/bin/env python3
"""compile-world-state.py v0 — patches auto fields in knowledge/world-state.yaml.

Usage:
  python scripts/compile-world-state.py           # patch and write
  python scripts/compile-world-state.py --dry-run  # print diff, no write
"""
import argparse, difflib, json, re, subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WS   = ROOT / "knowledge" / "world-state.yaml"


def _run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.stdout.strip() or None


def _grep(rel_path, pattern, group=1):
    p = ROOT / rel_path
    m = re.search(pattern, p.read_text("utf-8", errors="ignore") if p.exists() else "")
    return m.group(group).strip() if m else None


def _json(rel_path, key="version"):
    p = ROOT / rel_path
    return json.loads(p.read_text("utf-8")).get(key) if p.exists() else None


# ---------------------------------------------------------------------------
# Auto-field sources (update_mode=auto from field_meta)
# ---------------------------------------------------------------------------
AUTO_VERSIONS = {
    "gmail-agent":          lambda: _run(["git", "-C", str(ROOT / "gmail-agent"),
                                          "log", "-1", "--format=%H"]),
    "daszek":               lambda: _grep("daszek/daszek.php",
                                          r"DASZEK_VERSION',\s*'([^']+)'"),
    "kalk-top":             lambda: _json("kalk-top/package.json"),
    "top-instal-generator": lambda: _json("top-instal-generator/composer.json"),
    "fast-kalk":            lambda: _grep(
        "fast-kalk/wp-content/plugins/topinstal-lead-widget/topinstal-lead-widget.php",
        r"\* Version:\s*([\d.]+)"),
}


def collect():
    return {k: fn() for k, fn in AUTO_VERSIONS.items()}


def apply(text, vals, ts):
    lines, result = text.splitlines(keepends=True), []
    in_repos, repo, schema_done = False, None, False

    for line in lines:
        # insert compiled timestamp once, right after the schema: line
        if not schema_done and re.match(r"^schema:", line):
            result += [line, f"# compiled: {ts.isoformat(timespec='seconds')}\n"]
            schema_done = True
            continue

        # track repos: section boundaries
        if re.match(r"^repos:", line):
            in_repos = True
        elif re.match(r"^\w", line):          # any other top-level key
            in_repos, repo = False, None

        # track current repo name (2-space indent, no dots, no sub-keys)
        if in_repos:
            m = re.match(r"^  ([\w][\w-]*):\s*$", line)
            if m:
                repo = m.group(1)

        # patch updated_at (top-level)
        if re.match(r"^updated_at:", line):
            line = f"updated_at: {ts.strftime('%Y-%m-%d')}\n"

        # patch version_code within a known repo block
        elif in_repos and re.match(r"^    version_code:", line) and vals.get(repo):
            c = re.search(r"(#.*)$", line)
            suffix = f"  {c.group(1)}" if c else ""
            line = f"    version_code: {json.dumps(vals[repo])}{suffix}\n"

        result.append(line)

    return "".join(result)


def main():
    ap = argparse.ArgumentParser(description="compile-world-state v0")
    ap.add_argument("--dry-run", action="store_true", help="Print diff, do not write")
    args = ap.parse_args()

    original = WS.read_text("utf-8")
    ts   = datetime.now(timezone.utc)
    vals = collect()
    updated = apply(original, vals, ts)

    # report collected values
    print("Auto values collected:")
    for repo, v in vals.items():
        has_field = f"version_code:" in original and f"  {repo}:" in original
        note = "" if has_field else "  [no target field in YAML — collected only]"
        print(f"  {repo}: {v or '(not found)'}{note}")

    if original == updated:
        print("\nNo changes."); return

    diff = list(difflib.unified_diff(
        original.splitlines(), updated.splitlines(),
        fromfile="world-state.yaml (current)",
        tofile="world-state.yaml (compiled)",
        lineterm="",
    ))
    print(f"\nDiff ({len(diff)} lines):")
    print("\n".join(diff[:80]))

    if args.dry_run:
        print("\n[dry-run] No file written.")
    else:
        WS.write_text(updated, "utf-8")
        print(f"\nWritten: {WS.name}")


if __name__ == "__main__":
    main()
