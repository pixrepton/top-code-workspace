"""
Parse a JSONL conversation transcript and extract structured summary.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from parse_transcript_lib import (  # noqa: E402
    extract_text_content,
    extract_tool_calls,
    read_transcript,
    trim_text,
    write_summary,
)

__all__ = ["extract_text_content", "extract_tool_calls", "main", "trim_text"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Parse a JSONL transcript into a summary file.")
    parser.add_argument("input", help="Path to the JSONL transcript file")
    parser.add_argument("output", help="Path to the summary output file")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    transcript_path = os.path.abspath(args.input)
    output_path = os.path.abspath(args.output)

    if not os.path.isfile(transcript_path):
        print(f"ERROR: transcript not found: {transcript_path}", file=sys.stderr)
        return 1

    transcript = read_transcript(transcript_path)
    print(f"Total lines in transcript: {transcript.total_lines}")

    write_summary(output_path, transcript_path, transcript)

    print(f"\nWritten summary to: {output_path}")
    print(f"Parsed messages: {len(transcript.turns)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
