#!/usr/bin/env python3
"""Rotacja tokena Google OAuth.

Użycie:
    python scripts/rotate_google_token.py [--env-file .env.local-vps]

Co robi:
    1. Odświeża obecny token (sprawdza czy ważny)
    2. Unieważnia stary token (revoke)
    3. Uruchamia przepływ OAuth device code
    4. Zapisuje nowy token do pliku .env
    5. Testuje nowy token (GET 1 wiadomości)

Wymaga:
    - GOOGLE_CLIENT_ID i GOOGLE_CLIENT_SECRET w pliku .env
    - GOOGLE_REFRESH_TOKEN w pliku .env (istniejący, do wymiany)
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import webbrowser
from pathlib import Path
from typing import Any


def load_env(env_path: Path) -> dict[str, str]:
    """Wczytaj .env jako słownik, pomijając komentarze."""
    env: dict[str, str] = {}
    if not env_path.is_file():
        print(f"  ERROR: Nie znaleziono pliku {env_path}")
        return env
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        env[key.strip()] = val.strip().strip('"').strip("'")
    return env


def write_env(env_path: Path, env: dict[str, str]) -> None:
    """Nadpisz plik .env, zachowując strukturę."""
    lines: list[str] = []
    written_keys: set[str] = set()
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            lines.append(line)
            continue
        if "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in env and key not in written_keys:
                lines.append(f"{key}={env[key]}")
                written_keys.add(key)
                continue
        lines.append(line)
    # Dopisz brakujące klucze na końcu
    for key, val in env.items():
        if key not in written_keys:
            lines.append(f"{key}={val}")
            written_keys.add(key)
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def refresh_token(client_id: str, client_secret: str, refresh_token: str) -> dict[str, Any] | None:
    """Odświeża token, zwraca dict {'access_token', ...} lub None."""
    import requests  # type: ignore[import-not-found]

    resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=15,
    )
    if resp.status_code == 200:
        return resp.json()
    print(f"  REFRESH FAILED ({resp.status_code}): {resp.text[:200]}")
    return None


def revoke_token(access_token: str) -> bool:
    """Unieważnia token. Zwraca True jeśli sukces."""
    import requests  # type: ignore[import-not-found]

    resp = requests.post(
        "https://oauth2.googleapis.com/revoke",
        params={"token": access_token},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10,
    )
    return resp.status_code == 200


def device_code_flow(client_id: str) -> dict[str, Any] | None:
    """Przepływ OAuth device code.

    Zwraca dict {'refresh_token': ..., 'access_token': ...} lub None.
    """
    import time

    import requests  # type: ignore[import-not-found]

    # Krok 1: Zainicjuj device code flow
    resp = requests.post(
        "https://oauth2.googleapis.com/device/code",
        data={
            "client_id": client_id,
            "scope": "https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.send https://www.googleapis.com/auth/drive.readonly",
        },
        timeout=15,
    )
    if resp.status_code != 200:
        print(f"  DEVICE CODE FAILED ({resp.status_code}): {resp.text[:200]}")
        return None

    device_data = resp.json()
    print(f"\n  Otwieram przeglądarkę: {device_data.get('verification_url', '')}")
    print(f"  Kod: {device_data.get('user_code', '')}")
    print("  (Jeśli przeglądarka nie otworzyła się automatycznie, kliknij link powyżej)")
    webbrowser.open(device_data.get("verification_url", ""))

    # Krok 2: Czekaj na autoryzację (poll)
    device_code = device_data.get("device_code", "")
    interval = int(device_data.get("interval", 5))
    expires_in = int(device_data.get("expires_in", 1800))
    deadline = time.time() + expires_in

    while time.time() < deadline:
        time.sleep(interval)
        poll = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": client_id,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
            timeout=15,
        )
        poll_data = poll.json()
        if poll.status_code == 200:
            return poll_data
        error = poll_data.get("error", "")
        if error == "authorization_pending":
            continue  # Czekamy dalej
        if error == "slow_down":
            interval += 5
            continue
        print(f"  POLL ERROR: {error}")
        return None

    print("  TIMEOUT: Nie doczekano się autoryzacji.")
    return None


def test_token(client_id: str, refresh_token: str) -> bool:
    """Testuje token: odświeża i czyta 1 wiadomość z Gmail API."""
    import requests  # type: ignore[import-not-found]

    token_data = refresh_token(client_id, "", refresh_token)
    if not token_data:
        return False
    access_token = token_data.get("access_token", "")

    resp = requests.get(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages?maxResults=1",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15,
    )
    if resp.status_code == 200:
        print(f"  TEST OK: Odczytano {len(resp.json().get('messages', []))} wiadomości.")
        return True
    print(f"  TEST FAILED ({resp.status_code}): {resp.text[:200]}")
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Rotacja tokena OAuth (Google lub Daszek Bridge)")
    parser.add_argument(
        "--service",
        choices=["google", "daszek"],
        default="daszek",
        help="Który token rotować: 'google' (GOOGLE_REFRESH_TOKEN) lub 'daszek' (DASZEK_BRIDGE_TOKEN, domyślnie)",
    )
    parser.add_argument(
        "--env-file",
        default="",
        help="Ścieżka do pliku .env (domyślnie: szuka w gmail-agent/tools/gmail_audit/)",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Tryb nieinteraktywny: tylko sprawdza ważność tokena, nie uruchamia przepływu OAuth",
    )
    parser.add_argument(
        "--print-url-only",
        action="store_true",
        help="Tylko wydrukuj URL autoryzacji i zakończ (dla headless/CI)",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Tylko sprawdź czy token jest ważny, nie zmieniaj niczego",
    )
    args = parser.parse_args()

    # ── Service: Daszek Bridge Token ────────────────────────────────────
    if args.service == "daszek":
        import secrets

        # Znajdź plik .env
        env_path: Path | None = None
        if args.env_file:
            env_path = Path(args.env_file).resolve()
        else:
            candidates = [
                Path("gmail-agent/.env.vps"),
                Path("gmail-agent/tools/gmail_audit/.env"),
                Path(".env"),
            ]
            for c in candidates:
                if c.is_file():
                    env_path = c.resolve()
                    break
        if not env_path or not env_path.is_file():
            print("ERROR: Nie znaleziono pliku .env. Podaj --env-file.")
            return 1

        print(f"=== Rotacja tokena Daszek Bridge ===")
        print(f"  Plik .env: {env_path}")
        env = load_env(env_path)

        current_token = env.get("DASZEK_BRIDGE_TOKEN", "")
        if not current_token:
            print("ERROR: Brak DASZEK_BRIDGE_TOKEN w .env")
            return 1

        new_token = secrets.token_urlsafe(32)
        print(f"  Obecny token: {current_token[:16]}...")
        print(f"  Nowy token:   {new_token}")

        if args.validate_only:
            print(f"\n  [VALIDATE-ONLY] Token istnieje ({len(current_token)} znaków). Nic nie zmieniam.")
            return 0

        env["DASZEK_BRIDGE_TOKEN"] = new_token
        write_env(env_path, env)
        print(f"\n=== ROTACJA UDANA ===")
        print(f"  Nowy DASZEK_BRIDGE_TOKEN zapisany do {env_path}")
        print(f"  Zaktualizuj również token w Daszku (WordPress config) lub zsynchronizuj przez sync-local-stack-env.ps1")
        return 0

    # ── Service: Google OAuth ───────────────────────────────────────────

    # Znajdź plik .env
    env_path: Path | None = None
    if args.env_file:
        env_path = Path(args.env_file).resolve()
    else:
        candidates = [
            Path("gmail-agent/tools/gmail_audit/.env"),
            Path("gmail-agent/tools/gmail_audit/.env.local-vps"),
        ]
        for c in candidates:
            if c.is_file():
                env_path = c.resolve()
                break

    if not env_path or not env_path.is_file():
        print("ERROR: Nie znaleziono pliku .env. Podaj --env-file.")
        return 1

    print(f"=== Rotacja tokena Google OAuth ===")
    print(f"  Plik .env: {env_path}")
    env = load_env(env_path)
    if not env:
        return 1

    client_id = env.get("GOOGLE_CLIENT_ID", "")
    client_secret = env.get("GOOGLE_CLIENT_SECRET", "")
    old_refresh_token = env.get("GOOGLE_REFRESH_TOKEN", "")

    if not client_id or not client_secret:
        print("ERROR: Brak GOOGLE_CLIENT_ID lub GOOGLE_CLIENT_SECRET w .env")
        return 1
    if not old_refresh_token:
        print("ERROR: Brak GOOGLE_REFRESH_TOKEN w .env")
        return 1

    # --validate-only: tylko sprawdź token, nic nie zmieniaj
    if args.validate_only:
        print(f"\n[1/1] Walidacja tokena...")
        token_data = refresh_token(client_id, client_secret, old_refresh_token)
        if token_data:
            print(f"  TOKEN WAŻNY: {token_data.get('access_token', '')[:20]}...")
            return 0
        print(f"  TOKEN NIEWAŻNY")
        return 1

    print(f"\n[1/5] Odświeżanie obecnego tokena...")
    token_data = refresh_token(client_id, client_secret, old_refresh_token)
    if token_data:
        print(f"  Token ważny. Odświeżony access_token: {token_data.get('access_token', '')[:20]}...")
        access_token = token_data.get("access_token", "")
    else:
        print(f"  Token nieważny lub wygasł. Kontynuuję...")
        access_token = ""

    if access_token:
        print(f"\n[2/5] Unieważnianie starego tokena...")
        if revoke_token(access_token):
            print("  Stary token unieważniony.")
        else:
            print("  Nie udało się unieważnić (token mógł być już nieważny). Kontynuuję...")

    # --non-interactive: tylko test, żadnego przepływu OAuth
    if args.non_interactive:
        print(f"\n[NON-INTERACTIVE] Rotacja wymaga interakcji użytkownika.")
        print(f"  Uruchom bez --non-interactive, aby wykonać pełną rotację.")
        print(f"  Lub użyj --print-url-only aby dostać URL do autoryzacji.")
        return 0

    print(f"\n[3/5] Przepływ OAuth — nowy token...")

    # --print-url-only: wydrukuj URL i zakończ
    if args.print_url_only:
        import requests

        resp = requests.post(
            "https://oauth2.googleapis.com/device/code",
            data={
                "client_id": client_id,
                "scope": "https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.send https://www.googleapis.com/auth/drive.readonly",
            },
            timeout=15,
        )
        if resp.status_code != 200:
            print(f"ERROR: Nie udało się uzyskać URL: {resp.text[:200]}")
            return 1
        device_data = resp.json()
        print(f"\n  URL: {device_data.get('verification_url', '')}")
        print(f"  Kod: {device_data.get('user_code', '')}")
        print(f"  Po autoryzacji uruchom: python scripts/rotate_google_token.py --env-file {env_path}")
        return 0

    result = device_code_flow(client_id)
    if not result:
        print("ERROR: Nie uzyskano nowego tokena.")
        return 1

    new_refresh_token = result.get("refresh_token", "")
    if not new_refresh_token:
        print("ERROR: Odpowiedź OAuth nie zawiera refresh_token.")
        print(f"  Otrzymano: {list(result.keys())}")
        return 1

    print(f"\n[4/5] Zapis nowego tokena do .env...")
    env["GOOGLE_REFRESH_TOKEN"] = new_refresh_token
    write_env(env_path, env)
    print(f"  Nowy refresh_token zapisany.")

    print(f"\n[5/5] Test nowego tokena...")
    if test_token(client_id, new_refresh_token):
        print(f"\n=== ROTACJA UDANA ===")
        return 0
    print(f"\n=== ROTACJA ZAKOŃCZONA, ALE TEST NIE PRZESZEDŁ ===")
    print("Sprawdź czy zakresy OAuth są poprawne.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
