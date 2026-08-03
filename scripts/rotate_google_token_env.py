#!/usr/bin/env python3
"""Odczyt i bezpieczny zapis plikow .env dla rotacji tokenow."""

from __future__ import annotations

import os
from pathlib import Path


def _is_assignment(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.startswith("#"):
        return False
    return "=" in stripped


def _parse_env_line(line: str) -> tuple[str, str] | None:
    if not _is_assignment(line):
        return None
    key, _, val = line.strip().partition("=")
    return key.strip(), val.strip().strip('"').strip("'")


def load_env(env_path: Path) -> dict[str, str]:
    """Wczytaj .env jako słownik, pomijając komentarze."""
    env: dict[str, str] = {}
    if not env_path.is_file():
        print(f"  ERROR: Nie znaleziono pliku {env_path}")
        return env
    for line in env_path.read_text(encoding="utf-8").splitlines():
        parsed = _parse_env_line(line)
        if parsed is not None:
            env[parsed[0]] = parsed[1]
    return env


def _rewrite_line(line: str, env: dict[str, str], written_keys: set[str]) -> str:
    if not _is_assignment(line):
        return line
    key = line.strip().split("=", 1)[0].strip()
    if key in written_keys:
        return line
    if key not in env:
        return line
    written_keys.add(key)
    return f"{key}={env[key]}"


def render_env(existing_text: str, env: dict[str, str]) -> str:
    """Zbuduj tresc .env, nadpisujac znane klucze i dopisujac brakujace."""
    written_keys: set[str] = set()
    lines = [_rewrite_line(line, env, written_keys) for line in existing_text.splitlines()]
    lines.extend(f"{key}={val}" for key, val in env.items() if key not in written_keys)
    return "\n".join(lines) + "\n"


def write_env(env_path: Path, env: dict[str, str]) -> None:
    """Nadpisz plik .env, zachowując strukturę."""
    content = render_env(env_path.read_text(encoding="utf-8"), env)
    tmp_path = env_path.with_suffix(env_path.suffix + ".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    os.replace(tmp_path, env_path)
