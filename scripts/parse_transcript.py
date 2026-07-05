"""
Parse a JSONL conversation transcript and extract structured summary.
"""
import json
import os

TRANSCRIPT_PATH = r"C:\Users\compg\.cursor\projects\c-Users-compg-Desktop-top-code-workspace\agent-transcripts\0367e349-23c1-4cf2-85ff-a31af9402872\0367e349-23c1-4cf2-85ff-a31af9402872.jsonl"
OUTPUT_PATH = r"C:\Users\compg\.cursor\projects\c-Users-compg-Desktop-top-code-workspace\agent-tools\transcript-summary.txt"


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


def main():
    # Count lines first
    total_lines = 0
    with open(TRANSCRIPT_PATH, "r", encoding="utf-8") as f:
        for _ in f:
            total_lines += 1

    print(f"Total lines in transcript: {total_lines}")

    # Parse and group
    turns = []  # list of dicts with role, texts, tools
    errors = 0
    with open(TRANSCRIPT_PATH, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
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

    # Write output
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as out:
        out.write("=" * 80 + "\n")
        out.write("CONVERSATION TRANSCRIPT SUMMARY\n")
        out.write(f"Source: {TRANSCRIPT_PATH}\n")
        out.write(f"Total messages: {len(turns)}\n")
        out.write(f"Total lines in file: {total_lines}\n")
        out.write(f"JSON parse errors: {errors}\n")
        out.write("=" * 80 + "\n\n")

        for i, turn in enumerate(turns):
            role_label = "USER" if turn["role"] == "user" else "ASSISTANT" if turn["role"] == "assistant" else turn["role"].upper()
            out.write(f"--- Turn {i+1:4d} | Role: {role_label} ---\n")

            # Tool calls
            if turn["tools"]:
                out.write(f"  Tool calls ({len(turn['tools'])}):\n")
                for t in turn["tools"]:
                    out.write(f"    - {t['name']}")
                    if t["description"]:
                        out.write(f" : {t['description']}")
                    out.write("\n")

            # Text content
            if turn["texts"]:
                for t_idx, t in enumerate(turn["texts"]):
                    trimmed = trim_text(t, 500)
                    out.write(f"  Content:\n{trimmed}\n")
                    if t_idx < len(turn["texts"]) - 1:
                        out.write("  ---\n")

            if turn["tools"] or turn["texts"]:
                out.write("\n")

    print(f"\nWritten summary to: {OUTPUT_PATH}")
    print(f"Parsed messages: {len(turns)}")


if __name__ == "__main__":
    main()
