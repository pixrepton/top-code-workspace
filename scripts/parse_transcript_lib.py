"""Parsing and rendering helpers for JSONL conversation transcripts."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

TEXT_TRIM_CHARS = 500
DESCRIPTION_TRIM_CHARS = 300
INPUT_TRIM_CHARS = 200
RULE = "=" * 80
ROLE_LABELS = {"user": "USER", "assistant": "ASSISTANT"}


@dataclass
class Transcript:
    turns: list[dict[str, Any]] = field(default_factory=list)
    total_lines: int = 0
    errors: int = 0


def extract_text_content(content_list):
    """Extract concatenated text from content items."""
    texts = []
    for item in content_list:
        if item.get("type") == "text":
            texts.append(item.get("text", ""))
    return texts


def _tool_description(inp) -> str:
    if isinstance(inp, dict):
        return inp.get("description", "") or inp.get("path", "") or inp.get("command", "")
    if isinstance(inp, str):
        return inp[:INPUT_TRIM_CHARS]
    return str(inp)[:INPUT_TRIM_CHARS]


def extract_tool_calls(content_list):
    """Extract tool call info from content items."""
    tools = []
    for item in content_list:
        if item.get("type") == "tool_use":
            desc = _tool_description(item.get("input", {}))
            tools.append(
                {
                    "name": item.get("name", "?"),
                    "description": str(desc)[:DESCRIPTION_TRIM_CHARS],
                }
            )
    return tools


def trim_text(text, max_chars=TEXT_TRIM_CHARS):
    """Trim text to max_chars with ellipsis."""
    if len(text) > max_chars:
        return text[:max_chars] + "..."
    return text


def _turn_from_object(obj, line_no: int) -> dict[str, Any] | None:
    content_list = obj.get("message", {}).get("content", [])
    if not isinstance(content_list, list):
        print(f"  [WARN] Line {line_no}: content is not a list, skipping")
        return None
    return {
        "role": obj.get("role", "unknown"),
        "texts": extract_text_content(content_list),
        "tools": extract_tool_calls(content_list),
    }


def _consume_line(transcript: Transcript, line_no: int, line: str) -> None:
    if not line:
        return
    try:
        obj = json.loads(line)
    except json.JSONDecodeError as exc:
        print(f"  [WARN] JSON decode error on line {line_no}: {exc}")
        transcript.errors += 1
        return
    turn = _turn_from_object(obj, line_no)
    if turn is not None:
        transcript.turns.append(turn)


def read_transcript(transcript_path: str) -> Transcript:
    transcript = Transcript()
    with open(transcript_path, encoding="utf-8") as handle:
        for line_no, raw_line in enumerate(handle, 1):
            transcript.total_lines += 1
            _consume_line(transcript, line_no, raw_line.strip())
    return transcript


def role_label(role: str) -> str:
    return ROLE_LABELS.get(role, role.upper())


def render_header(source: str, transcript: Transcript) -> str:
    return (
        f"{RULE}\n"
        "CONVERSATION TRANSCRIPT SUMMARY\n"
        f"Source: {source}\n"
        f"Total messages: {len(transcript.turns)}\n"
        f"Total lines in file: {transcript.total_lines}\n"
        f"JSON parse errors: {transcript.errors}\n"
        f"{RULE}\n\n"
    )


def _render_tools(tools) -> str:
    if not tools:
        return ""
    parts = [f"  Tool calls ({len(tools)}):\n"]
    for tool in tools:
        suffix = f" : {tool['description']}" if tool["description"] else ""
        parts.append(f"    - {tool['name']}{suffix}\n")
    return "".join(parts)


def _render_texts(texts) -> str:
    parts = []
    for index, text in enumerate(texts):
        parts.append(f"  Content:\n{trim_text(text, TEXT_TRIM_CHARS)}\n")
        if index < len(texts) - 1:
            parts.append("  ---\n")
    return "".join(parts)


def render_turn(number: int, turn) -> str:
    body = _render_tools(turn["tools"]) + _render_texts(turn["texts"])
    header = f"--- Turn {number:4d} | Role: {role_label(turn['role'])} ---\n"
    return header + body + ("\n" if body else "")


def write_summary(output_path: str, source: str, transcript: Transcript) -> None:
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as out:
        out.write(render_header(source, transcript))
        for number, turn in enumerate(transcript.turns, 1):
            out.write(render_turn(number, turn))
