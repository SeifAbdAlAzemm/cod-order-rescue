"""Non-billable capability and pricing checks per profile.

Declared tool support = what model metadata says. Verified tool support = a LIVE run in which the
model actually made a valid tool call (computed by the evaluation, never assumed here).
"""

from __future__ import annotations

import json
import os
import urllib.request

OPENROUTER_HOST = "openrouter.ai"
ANTHROPIC_DEFAULT_URL = "https://api.anthropic.com"
# Hosts a credential may be sent to. Anything else (including a localhost server) never receives a key.
TRUSTED_KEY_HOSTS = {"api.anthropic.com", "openrouter.ai", "router.huggingface.co", "api.openai.com"}


def key_destination(profile) -> tuple[str, bool]:
    """(endpoint URL, trusted?) for a profile. Only https endpoints on allowlisted hosts are trusted."""
    from urllib.parse import urlparse
    url = profile.base_url or (ANTHROPIC_DEFAULT_URL if profile.provider == "anthropic" else "")
    parsed = urlparse(url)
    return url, parsed.scheme == "https" and parsed.hostname in TRUSTED_KEY_HOSTS and not parsed.username


def is_openrouter(profile) -> bool:
    return profile.provider == "openai_compatible" and OPENROUTER_HOST in profile.base_url


def _get_json(url: str, timeout: float = 20.0, headers: dict | None = None) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "cod-order-rescue-check", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - https enforced by config
        return json.load(resp)


def openrouter_model_metadata(profile, fetch=None) -> dict | None:
    """Public models list (no key, not billed). None if the model is not listed."""
    data = (fetch or _get_json)(profile.base_url.rstrip("/") + "/models")["data"]
    m = next((x for x in data if x.get("id") == profile.model), None)
    if m is None:
        return None
    p = m.get("pricing") or {}

    def price(key):
        try:
            return float(p.get(key)) * 1_000_000 if p.get(key) is not None else None  # USD per token -> per 1M
        except (TypeError, ValueError):
            return None

    return {"declared_tools": "tools" in (m.get("supported_parameters") or []),
            "price_input_per_mtok": price("prompt"), "price_output_per_mtok": price("completion"),
            "context_length": m.get("context_length")}


def check_profile(settings, profile, fetch=None, api_key: str | None = None) -> dict:
    """Returns a report; never makes a billable call and never prints or returns the key.
    api_key: optional in-memory key (dashboard); otherwise the env var named by the profile."""
    key = api_key or os.environ.get(profile.api_key_env)
    url, trusted = key_destination(profile)
    report = {"profile": profile.name, "provider": profile.provider, "model": profile.model,
              "base_url": profile.base_url or "(provider default)", "api_key_env": profile.api_key_env,
              "key_present": bool(key), "key_destination_trusted": trusted,
              "pricing_status": profile.pricing.status, "pricing_source": profile.pricing.source,
              "model_listed": None, "tool_support": "unknown", "pricing_check": "not_checked", "problems": []}
    if profile.pricing.status == "unknown":
        report["problems"].append("pricing unknown: LIVE refused (missing pricing is never treated as free)")
    if not trusted:
        report["problems"].append(f"endpoint {url!r} is not an allowlisted https host: credentials are never sent there")
    try:
        if is_openrouter(profile):
            meta = openrouter_model_metadata(profile, fetch)
            report["model_listed"] = meta is not None
            if meta is None:
                report["problems"].append("model not listed by OpenRouter")
            else:
                report["tool_support"] = "declared" if meta["declared_tools"] else "not_declared"
                if not meta["declared_tools"]:
                    report["problems"].append("model metadata does not declare tool calling")
                api_in, api_out = meta["price_input_per_mtok"], meta["price_output_per_mtok"]
                report["listed_prices_per_mtok"] = {"input": api_in, "output": api_out}
                if api_in is None or api_out is None:
                    report["pricing_check"] = "listed price missing"
                    if profile.pricing.status == "verified_free":
                        report["problems"].append("cannot verify zero price: listing has no price")
                elif profile.pricing.status == "verified_free":
                    ok = api_in == 0 and api_out == 0
                    report["pricing_check"] = "zero price confirmed" if ok else "NOT FREE per listing"
                    if not ok:
                        report["problems"].append(f"configured verified_free but listed {api_in}/{api_out} per 1M")
                elif profile.pricing.status == "known":
                    ok = abs(api_in - profile.pricing.input) < 1e-9 and abs(api_out - profile.pricing.output) < 1e-9
                    report["pricing_check"] = "matches listing" if ok else f"differs from listing {api_in}/{api_out}"
        elif profile.provider == "anthropic":
            if report["key_present"]:
                import anthropic
                m = anthropic.Anthropic(api_key=key, base_url=url).models.retrieve(profile.model)
                report["model_listed"] = m.id == profile.model
                report["tool_support"] = "declared (Messages API tool use)"
            if profile.pricing.status == "verified_free":
                report["problems"].append("verified_free cannot be confirmed for this provider automatically")
        else:  # generic OpenAI-compatible endpoint
            if report["key_present"] and trusted:
                import openai
                ids = [m.id for m in openai.OpenAI(api_key=key, base_url=profile.base_url).models.list()]
                report["model_listed"] = profile.model in ids
            report["tool_support"] = "unknown (endpoint does not declare capabilities)"
            if profile.pricing.status == "verified_free":
                report["problems"].append("verified_free cannot be confirmed for this endpoint automatically")
    except Exception as e:  # network/SDK errors are reported, not raised
        report["problems"].append(f"check failed: {type(e).__name__}: {str(e)[:160]}")
    if not report["key_present"]:
        report["problems"].append(f"{profile.api_key_env} not set (environment or .env)")
    report["live_ready"] = not report["problems"]
    return report
