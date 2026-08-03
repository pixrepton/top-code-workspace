"""
Parse a JSONL conversation transcript and extract structured summary.
"""
import argparse
import json
import os
import sys


def extract_text_content(content_list):
    """Extract concatenated text from content items."""
    texts = []
    for item in content_list:
        if item.get("type") == "text":
            texts.append(item.get("text", ""))
    return texts


def extract_tool_calls(content_list):
    """Extract tool call info from content items."""
    tools = []
    for item in content_list:
        if item.get("type") == "tool_use":
            name = item.get("name", "?")
            inp = item.get("input", {})
            if isinstance(inp, dict):
                desc = inp.get("description", "") or inp.get("path", "") or inp.get("command", "")
            elif isinstance(inp, str):
                desc = inp[:200]
            else:
                desc = str(inp)[:200]
            tools.append({"name": name, "description": str(desc)[:300]})
    return tools


def trim_text(text, max_chars=500):
    """Trim text to max_chars with ellipsis."""
    if len(text) > max_chars:
        return text[:max_chars] + "..."
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse a JSONL transcript into a summary file.")
    parser.add_argument("input", help="Path to the JSONL transcript file")
    parser.add_argument("output", help="Path to the summary output file")
    args = parser.parse_args()

    transcript_path = os.path.abspath(args.input)
    output_path = os.path.abspath(args.output)

    if not os.path.isfile(transcript_path):
        print(f"ERROR: transcript not found: {transcript_path}", file=sys.stderr)
        return 1

    turns = []
    errors = 0
    total_lines = 0

    with open(transcript_path, encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            total_lines += 1
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"  [WARN] JSON decode error on line {line_no}: {e}")
                errors += 1
                continue

            role = obj.get("role", "unknown")
            msg = obj.get("message", {})
            content_list = msg.get("content", [])

            if not isinstance(content_list, list):
                print(f"  [WARN] Line {line_no}: content is not a list, skipping")
                continue

            texts = extract_text_content(content_list)
            tools = extract_tool_calls(content_list)

            turns.append({
                "role": role,
                "texts": texts,
                "tools": tools,
            })

    print(f"Total lines in transcript: {total_lines}")

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as out:
        out.write("=" * 80 + "\n")
        out.write("CONVERSATION TRANSCRIPT SUMMARY\n")
        out.write(f"Source: {transcript_path}\n")
        out.write(f"Total messages: {len(turns)}\n")
        out.write(f"Total lines in file: {total_lines}\n")
        out.write(f"JSON parse errors: {errors}\n")
        out.write("=" * 80 + "\n\n")

        for i, turn in enumerate(turns):
            role_label = "USER" if turn["role"] == "user" else "ASSISTANT" if turn["role"] == "assistant" else turn["role"].upper()
            out.write(f"--- Turn {i+1:4d} | Role: {role_label} ---\n")

            if turn["tools"]:
                out.write(f"  Tool calls ({len(turn['tools'])}):\n")
                for t in turn["tools"]:
                    out.write(f"    - {t['name']}")
                    if t["description"]:
                        out.write(f" : {t['description']}")
                    out.write("\n")

            if turn["texts"]:
                for t_idx, t in enumerate(turn["texts"]):
                    trimmed = trim_text(t, 500)
                    out.write(f"  Content:\n{trimmed}\n")
                    if t_idx < len(turn["texts"]) - 1:
                        out.write("  ---\n")

            if turn["tools"] or turn["texts"]:
                out.write("\n")

    print(f"\nWritten summary to: {output_path}")
    print(f"Parsed messages: {len(turns)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
