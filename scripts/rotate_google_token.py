#!/usr/bin/env python3
"""Rotacja tokena Google OAuth.

Użycie:
    python scripts/rotate_google_token.py [--env-file .env.local-vps]

Co robi:
    1. Odświeża obecny token (sprawdza czy ważny)
    2. Uruchamia przepływ OAuth device code
    3. Zapisuje nowy token do pliku .env
    4. Testuje nowy token (GET 1 wiadomości)
    5. Unieważnia stary token (revoke) — dopiero po udanej rotacji

Wymaga:
    - GOOGLE_CLIENT_ID i GOOGLE_CLIENT_SECRET w pliku .env
    - GOOGLE_REFRESH_TOKEN w pliku .env (istniejący, do wymiany)
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rotate_google_token_env import load_env, write_env  # noqa: E402
from rotate_google_token_oauth import (  # noqa: E402
    device_code_flow,
    refresh_token,
    request_device_code,
    revoke_token,
    test_token,
)

GOOGLE_ENV_CANDIDATES = (
    Path("gmail-agent/tools/gmail_audit/.env"),
    Path("gmail-agent/tools/gmail_audit/.env.local-vps"),
)
DASZEK_ENV_CANDIDATES = (
    Path("gmail-agent/.env.vps"),
    Path("gmail-agent/tools/gmail_audit/.env"),
    Path(".env"),
)


def build_parser() -> argparse.ArgumentParser:
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
    return parser


def resolve_env_path(explicit: str, candidates: Iterable[Path]) -> Path | None:
    """Zwroc istniejacy plik .env: jawny --env-file albo pierwszy kandydat."""
    if explicit:
        path = Path(explicit).resolve()
        return path if path.is_file() else None
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None


# ── Service: Daszek Bridge Token ────────────────────────────────────────


def rotate_daszek(args: argparse.Namespace) -> int:
    import secrets

    env_path = resolve_env_path(args.env_file, DASZEK_ENV_CANDIDATES)
    if env_path is None:
        print("ERROR: Nie znaleziono pliku .env. Podaj --env-file.")
        return 1

    print("=== Rotacja tokena Daszek Bridge ===")
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
    print("\n=== ROTACJA UDANA ===")
    print(f"  Nowy DASZEK_BRIDGE_TOKEN zapisany do {env_path}")
    print("  Zaktualizuj również token w Daszku (WordPress config) lub zsynchronizuj przez sync-local-stack-env.ps1")
    return 0


# ── Service: Google OAuth — etapy ───────────────────────────────────────


def google_credentials(env: dict[str, str]) -> tuple[str, str, str] | None:
    """Zwroc (client_id, client_secret, refresh_token) albo None po wypisaniu bledu."""
    client_id = env.get("GOOGLE_CLIENT_ID", "")
    client_secret = env.get("GOOGLE_CLIENT_SECRET", "")
    old_refresh_token = env.get("GOOGLE_REFRESH_TOKEN", "")
    if not client_id or not client_secret:
        print("ERROR: Brak GOOGLE_CLIENT_ID lub GOOGLE_CLIENT_SECRET w .env")
        return None
    if not old_refresh_token:
        print("ERROR: Brak GOOGLE_REFRESH_TOKEN w .env")
        return None
    return client_id, client_secret, old_refresh_token


def stage_validate_only(client_id: str, client_secret: str, old_refresh_token: str) -> int:
    print("\n[1/1] Walidacja tokena...")
    token_data = refresh_token(client_id, client_secret, old_refresh_token)
    if token_data:
        print(f"  TOKEN WAŻNY: {token_data.get('access_token', '')[:20]}...")
        return 0
    print("  TOKEN NIEWAŻNY")
    return 1


def stage_refresh_current(client_id: str, client_secret: str, old_refresh_token: str) -> str:
    """Odswiez obecny token i zwroc access_token (pusty gdy token wygasl)."""
    print("\n[1/5] Odświeżanie obecnego tokena...")
    token_data = refresh_token(client_id, client_secret, old_refresh_token)
    if not token_data:
        print("  Token nieważny lub wygasł. Kontynuuję...")
        return ""
    print(f"  Token ważny. Odświeżony access_token: {token_data.get('access_token', '')[:20]}...")
    return token_data.get("access_token", "")


def stage_report_non_interactive() -> int:
    print("\n[NON-INTERACTIVE] Rotacja wymaga interakcji użytkownika.")
    print("  Uruchom bez --non-interactive, aby wykonać pełną rotację.")
    print("  Lub użyj --print-url-only aby dostać URL do autoryzacji.")
    return 0


def stage_print_url(client_id: str, env_path: Path) -> int:
    device_data, _status_code, body = request_device_code(client_id)
    if device_data is None:
        print(f"ERROR: Nie udało się uzyskać URL: {body}")
        return 1
    print(f"\n  URL: {device_data.get('verification_url', '')}")
    print(f"  Kod: {device_data.get('user_code', '')}")
    print(f"  Po autoryzacji uruchom: python scripts/rotate_google_token.py --env-file {env_path}")
    return 0


def stage_acquire_refresh_token(client_id: str) -> str | None:
    result = device_code_flow(client_id)
    if not result:
        print("ERROR: Nie uzyskano nowego tokena.")
        return None
    new_refresh_token = result.get("refresh_token", "")
    if not new_refresh_token:
        print("ERROR: Odpowiedź OAuth nie zawiera refresh_token.")
        print(f"  Otrzymano: {list(result.keys())}")
        return None
    return new_refresh_token


def stage_persist(env_path: Path, env: dict[str, str], new_refresh_token: str) -> None:
    print("\n[3/5] Zapis nowego tokena do .env...")
    env["GOOGLE_REFRESH_TOKEN"] = new_refresh_token
    write_env(env_path, env)
    print("  Nowy refresh_token zapisany.")


def stage_verify(client_id: str, client_secret: str, new_refresh_token: str) -> bool:
    print("\n[4/5] Test nowego tokena...")
    if test_token(client_id, client_secret, new_refresh_token):
        return True
    print("\n=== ROTACJA ZAKOŃCZONA, ALE TEST NIE PRZESZEDŁ ===")
    print("Sprawdź czy zakresy OAuth są poprawne.")
    return False


def stage_revoke(old_access_token: str) -> None:
    if not old_access_token:
        return
    print("\n[5/5] Unieważnianie starego tokena...")
    if revoke_token(old_access_token):
        print("  Stary token unieważniony.")
    else:
        print("  Nie udało się unieważnić (token mógł być już nieważny).")


GoogleContext = tuple[Path, dict[str, str], tuple[str, str, str]]


def load_google_context(env_file: str) -> GoogleContext | None:
    """Zwroc (env_path, env, credentials) albo None po wypisaniu bledu."""
    env_path = resolve_env_path(env_file, GOOGLE_ENV_CANDIDATES)
    if env_path is None:
        print("ERROR: Nie znaleziono pliku .env. Podaj --env-file.")
        return None

    print("=== Rotacja tokena Google OAuth ===")
    print(f"  Plik .env: {env_path}")
    env = load_env(env_path)
    if not env:
        return None

    credentials = google_credentials(env)
    if credentials is None:
        return None
    return env_path, env, credentials


def rotate_google(args: argparse.Namespace) -> int:
    context = load_google_context(args.env_file)
    if context is None:
        return 1
    env_path, env, credentials = context
    client_id, client_secret, old_refresh_token = credentials

    if args.validate_only:
        return stage_validate_only(client_id, client_secret, old_refresh_token)

    old_access_token = stage_refresh_current(client_id, client_secret, old_refresh_token)
    if args.non_interactive:
        return stage_report_non_interactive()

    print("\n[2/5] Przepływ OAuth — nowy token...")
    if args.print_url_only:
        return stage_print_url(client_id, env_path)

    new_refresh_token = stage_acquire_refresh_token(client_id)
    if new_refresh_token is None:
        return 1

    stage_persist(env_path, env, new_refresh_token)
    if not stage_verify(client_id, client_secret, new_refresh_token):
        return 1

    stage_revoke(old_access_token)
    print("\n=== ROTACJA UDANA ===")
    return 0


def main() -> int:
    args = build_parser().parse_args()
    if args.service == "daszek":
        return rotate_daszek(args)
    return rotate_google(args)


if __name__ == "__main__":
    sys.exit(main())
