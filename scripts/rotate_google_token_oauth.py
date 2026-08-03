#!/usr/bin/env python3
"""Operacje OAuth Google uzywane przez rotacje tokena."""

from __future__ import annotations

import webbrowser
from typing import Any

TOKEN_URL = "https://oauth2.googleapis.com/token"
DEVICE_CODE_URL = "https://oauth2.googleapis.com/device/code"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GMAIL_MESSAGES_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages?maxResults=1"
SCOPES = (
    "https://www.googleapis.com/auth/gmail.readonly "
    "https://www.googleapis.com/auth/gmail.send "
    "https://www.googleapis.com/auth/drive.readonly"
)


def refresh_token(client_id: str, client_secret: str, refresh_token: str) -> dict[str, Any] | None:
    """Odświeża token, zwraca dict {'access_token', ...} lub None."""
    import requests  # type: ignore[import-not-found]

    resp = requests.post(
        TOKEN_URL,
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
        REVOKE_URL,
        params={"token": access_token},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10,
    )
    return resp.status_code == 200


def request_device_code(client_id: str) -> tuple[dict[str, Any] | None, int, str]:
    """Inicjuje device code flow. Zwraca (device_data|None, status_code, body)."""
    import requests  # type: ignore[import-not-found]

    resp = requests.post(
        DEVICE_CODE_URL,
        data={"client_id": client_id, "scope": SCOPES},
        timeout=15,
    )
    if resp.status_code == 200:
        return resp.json(), resp.status_code, ""
    return None, resp.status_code, resp.text[:200]


def _announce_device_code(device_data: dict[str, Any]) -> None:
    print(f"\n  Otwieram przeglądarkę: {device_data.get('verification_url', '')}")
    print(f"  Kod: {device_data.get('user_code', '')}")
    print("  (Jeśli przeglądarka nie otworzyła się automatycznie, kliknij link powyżej)")
    webbrowser.open(device_data.get("verification_url", ""))


def _poll_device_token_once(client_id: str, device_code: str) -> tuple[str, dict[str, Any]]:
    """Jeden krok pollingu. Zwraca (state, payload) gdzie state to ok/pending/slow_down/error."""
    import requests  # type: ignore[import-not-found]

    poll = requests.post(
        TOKEN_URL,
        data={
            "client_id": client_id,
            "device_code": device_code,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        },
        timeout=15,
    )
    poll_data = poll.json()
    if poll.status_code == 200:
        return "ok", poll_data
    error = poll_data.get("error", "")
    if error == "authorization_pending":
        return "pending", poll_data
    if error == "slow_down":
        return "slow_down", poll_data
    return "error", poll_data


def _await_device_authorization(client_id: str, device_data: dict[str, Any]) -> dict[str, Any] | None:
    import time

    device_code = device_data.get("device_code", "")
    interval = int(device_data.get("interval", 5))
    deadline = time.time() + int(device_data.get("expires_in", 1800))

    while time.time() < deadline:
        time.sleep(interval)
        state, payload = _poll_device_token_once(client_id, device_code)
        if state == "ok":
            return payload
        if state == "pending":
            continue
        if state == "slow_down":
            interval += 5
            continue
        print(f"  POLL ERROR: {payload.get('error', '')}")
        return None

    print("  TIMEOUT: Nie doczekano się autoryzacji.")
    return None


def device_code_flow(client_id: str) -> dict[str, Any] | None:
    """Przepływ OAuth device code.

    Zwraca dict {'refresh_token': ..., 'access_token': ...} lub None.
    """
    device_data, status_code, body = request_device_code(client_id)
    if device_data is None:
        print(f"  DEVICE CODE FAILED ({status_code}): {body}")
        return None
    _announce_device_code(device_data)
    return _await_device_authorization(client_id, device_data)


def test_token(client_id: str, client_secret: str, token_refresh: str) -> bool:
    """Testuje token: odświeża i czyta 1 wiadomość z Gmail API."""
    import requests  # type: ignore[import-not-found]

    token_data = refresh_token(client_id, client_secret, token_refresh)
    if not token_data:
        return False
    access_token = token_data.get("access_token", "")

    resp = requests.get(
        GMAIL_MESSAGES_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15,
    )
    if resp.status_code == 200:
        print(f"  TEST OK: Odczytano {len(resp.json().get('messages', []))} wiadomości.")
        return True
    print(f"  TEST FAILED ({resp.status_code}): {resp.text[:200]}")
    return False
