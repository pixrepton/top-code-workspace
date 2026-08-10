#!/usr/bin/env python3
"""Read-only inventory of the live LLM provider pool (CL-05).

Why this exists: the FIX-RT01 telemetry made a degraded provider pool visible for the first time
(`openai_chat` -> `quota_exhausted`, at least one Groq key -> `401 invalid_api_key`). The repaired
runtime absorbs that, but "absorbed" is not "understood", and a pool with unknown credential state
is a live operational risk.

This performs one minimal smoke call per configured credential slot and classifies the result. It
mutates nothing.

SECRETS: no API key, Authorization header, or secret env value is ever printed or written. Each
slot is identified by its position and a short one-way fingerprint (`sha256(key)[:12]`), which is
enough for an operator to tell *which* credential is bad without the value being disclosed.

Run inside the runtime container so it sees the real configuration:

    docker exec gmail-agent-nodeb-api python /tmp/provider_pool_triage.py
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from typing import Any

sys.path.insert(0, "/app/tools/gmail_audit")

import requests  # noqa: E402
from config import load_settings  # noqa: E402
from llm_provider_router import classify_provider_error  # noqa: E402


SMOKE_PROMPT = [{"role": "user", "content": "ping"}]


def fingerprint(secret: str) -> str:
    """One-way slot identity. Never reversible to the credential."""
    value = str(secret or "").strip()
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


class _Err(RuntimeError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = dict(details or {})


def smoke_openai_compatible(*, url: str, api_key: str, model: str, timeout: float = 20.0) -> dict[str, Any]:
    """One tiny chat completion. max_tokens=1 keeps the probe close to free."""
    started = time.monotonic()
    try:
        response = requests.post(
            url,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            json={"model": model, "messages": SMOKE_PROMPT, "max_tokens": 1},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        return {
            "reachable": False,
            "auth_valid": None,
            "http_status": None,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "error_class": classify_provider_error(_Err(f"Failed to connect: {exc}")).error_class,
            "error": str(exc)[:200],
        }

    latency_ms = int((time.monotonic() - started) * 1000)
    body: dict[str, Any] = {}
    try:
        body = response.json()
    except ValueError:
        body = {}
    message = str(((body or {}).get("error") or {}).get("message") or response.text or "")[:300]

    if response.status_code < 400:
        return {
            "reachable": True, "auth_valid": True, "http_status": response.status_code,
            "latency_ms": latency_ms, "error_class": None, "error": "",
        }

    info = classify_provider_error(_Err(f"{response.status_code} {message}", details={"status_code": response.status_code}))
    return {
        "reachable": True,
        "auth_valid": response.status_code not in (401, 403),
        "http_status": response.status_code,
        "latency_ms": latency_ms,
        "error_class": info.error_class,
        "error": message,
    }


def classify_slot(slot: dict[str, Any]) -> str:
    """CODE_DEFECT / CONFIG_DEFECT / CREDENTIAL_DEFECT / QUOTA_CAPACITY / EXPECTED_UNCONFIGURED / HEALTHY."""
    if not slot["credential_configured"]:
        return "EXPECTED_UNCONFIGURED"
    probe = slot.get("probe") or {}
    if probe.get("auth_valid") is True and not probe.get("error_class"):
        return "HEALTHY"
    error_class = probe.get("error_class")
    if error_class == "auth":
        return "CREDENTIAL_DEFECT"
    if error_class in {"quota_exhausted", "rate_limit"}:
        return "QUOTA_CAPACITY"
    if error_class in {"not_found", "contract"}:
        return "CONFIG_DEFECT"
    if probe.get("reachable") is False:
        return "CONFIG_DEFECT"
    return "UNKNOWN"


def build_inventory() -> dict[str, Any]:
    settings = load_settings(require_groq=False, require_google=False)
    slots: list[dict[str, Any]] = []

    def add(provider: str, slot_id: str, credential: str, *, model: str, url: str, probe_it: bool = True) -> None:
        configured = bool(str(credential or "").strip())
        slot: dict[str, Any] = {
            "provider": provider,
            "slot": slot_id,
            "credential_configured": configured,
            "credential_fingerprint": fingerprint(credential),
            "credential_length": len(str(credential or "").strip()) or None,
            "model_configured": model,
            "endpoint": url,
            "probe": None,
        }
        if configured and probe_it and url:
            slot["probe"] = smoke_openai_compatible(url=url, api_key=credential, model=model)
        slot["classification"] = classify_slot(slot)
        slots.append(slot)

    # Primary lane: llm_primary_provider = openai_chat, pointed at an OpenAI-compatible endpoint.
    add(
        "openai_chat", "OPENAI_COMPAT_API_KEY",
        getattr(settings, "openai_compat_api_key", ""),
        model=str(getattr(settings, "groq_model", "") or ""),
        url=str(getattr(settings, "openai_chat_completions_url", "") or ""),
    )

    # Groq key pool: each slot probed independently so one dead key is attributable.
    groq_keys = tuple(getattr(settings, "groq_api_keys", ()) or ())
    groq_url = str(getattr(settings, "groq_base_url", "") or "").rstrip("/") + "/openai/v1/chat/completions"
    if not groq_keys:
        single = str(getattr(settings, "groq_api_key", "") or "")
        groq_keys = (single,) if single else ()
    for index, key in enumerate(groq_keys, start=1):
        add("groq", f"GROQ_API_KEY_SLOT_{index}", key,
            model=str(getattr(settings, "groq_native_model", "") or ""), url=groq_url)

    # Declared fallbacks and optional tiers.
    cerebras_keys = tuple(getattr(settings, "cerebras_api_keys", ()) or ())
    add("cerebras", "CEREBRAS_API_KEY", cerebras_keys[0] if cerebras_keys else "",
        model=str(getattr(settings, "cerebras_model", "") or ""),
        url=str(getattr(settings, "cerebras_base_url", "") or "").rstrip("/") + "/chat/completions")
    add("nvidia", "NVIDIA_API_KEY", getattr(settings, "nvidia_api_key", ""),
        model=str(getattr(settings, "nvidia_model", "") or ""),
        url=str(getattr(settings, "nvidia_base_url", "") or "").rstrip("/") + "/chat/completions")
    add("openrouter", "OPENROUTER_API_KEY", getattr(settings, "openrouter_api_key", ""),
        model=str(getattr(settings, "groq_model", "") or ""),
        url=str(getattr(settings, "openrouter_base_url", "") or "").rstrip("/") + "/chat/completions")
    add("deepseek", "DEEPSEEK_API_KEY", getattr(settings, "deepseek_api_key", ""),
        model=str(getattr(settings, "deepseek_model", "") or ""),
        url=str(getattr(settings, "deepseek_base_url", "") or "").rstrip("/") + "/chat/completions")
    add("anthropic", "ANTHROPIC_API_KEY", getattr(settings, "anthropic_api_key", ""),
        model=str(getattr(settings, "anthropic_model", "") or ""), url="", probe_it=False)

    active_chain = [str(getattr(settings, "llm_primary_provider", "") or "")] + list(
        getattr(settings, "llm_fallback_providers", ()) or ()
    )
    healthy_in_chain = [
        s["provider"] for s in slots
        if s["provider"] in active_chain and s["classification"] == "HEALTHY"
    ]

    return {
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "note": "No API key, Authorization header or secret value appears in this document.",
        "active_provider_chain": active_chain,
        "healthy_providers_in_active_chain": sorted(set(healthy_in_chain)),
        "stage_budget_sec": getattr(settings, "llm_stage_budget_sec", None),
        "http_timeout_sec": getattr(settings, "http_timeout", None),
        "slots": slots,
        "summary": {
            classification: sum(1 for s in slots if s["classification"] == classification)
            for classification in sorted({s["classification"] for s in slots})
        },
    }


def main() -> int:
    inventory = build_inventory()
    print(json.dumps(inventory, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
