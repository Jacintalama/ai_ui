"""Model Fusion engine: fan a prompt out to a panel of models and have a judge
synthesize one answer. Pure logic (registry, presets, per-provider calls,
fan-out, judge). No FastAPI here - the route layer wraps this. Only models in
PROVIDER_REGISTRY are ever callable, which is the "only models available to our
system" gate."""
import asyncio
import logging
import os
from dataclasses import dataclass

import httpx

logger = logging.getLogger("tasks.fusion")

OPENAI_BASE = os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1").rstrip("/")
ANTHROPIC_BASE = "https://api.anthropic.com/v1"


@dataclass(frozen=True)
class ModelSpec:
    provider: str   # "openai" | "anthropic"
    api_model: str
    contract: str   # "openai_new" | "openai_legacy" | "anthropic"


PROVIDER_REGISTRY: dict[str, ModelSpec] = {
    # OpenAI - newer reasoning/GPT-5 models need max_completion_tokens, no temperature.
    "gpt-5": ModelSpec("openai", "gpt-5", "openai_new"),
    "gpt-5.5": ModelSpec("openai", "gpt-5.5", "openai_new"),
    "o3": ModelSpec("openai", "o3", "openai_new"),
    # OpenAI - legacy contract (max_tokens + temperature ok).
    "gpt-4o": ModelSpec("openai", "gpt-4o", "openai_legacy"),
    "gpt-4.1": ModelSpec("openai", "gpt-4.1", "openai_legacy"),
    # Anthropic.
    "claude-opus-4-8": ModelSpec("anthropic", "claude-opus-4-8", "anthropic"),
    "claude-opus-4-5": ModelSpec("anthropic", "claude-opus-4-5", "anthropic"),
    "claude-sonnet-5": ModelSpec("anthropic", "claude-sonnet-5", "anthropic"),
    "claude-fable-5": ModelSpec("anthropic", "claude-fable-5", "anthropic"),
    "claude-haiku-4-5-20251001": ModelSpec("anthropic", "claude-haiku-4-5-20251001", "anthropic"),
}

_DEFAULT_PRESETS = {
    "quality": {"panel": ["gpt-5.5", "claude-opus-4-8"], "judge": "claude-opus-4-8"},
    "budget": {"panel": ["gpt-4o", "claude-haiku-4-5-20251001"], "judge": "gpt-4o"},
}


def _load_presets() -> dict[str, dict]:
    """Presets from env overrides (comma-lists) falling back to defaults.
    Every referenced model must be in the registry, else ValueError."""
    presets = {}
    for name, default in _DEFAULT_PRESETS.items():
        up = name.upper()
        panel_env = os.environ.get(f"FUSION_{up}_PANEL", "")
        judge_env = os.environ.get(f"FUSION_{up}_JUDGE", "")
        panel = [m.strip() for m in panel_env.split(",") if m.strip()] or list(default["panel"])
        judge = judge_env.strip() or default["judge"]
        for m in panel + [judge]:
            if m not in PROVIDER_REGISTRY:
                raise ValueError(f"preset {name}: unknown model {m!r} (not in registry)")
        presets[name] = {"panel": panel[:4], "judge": judge}  # hard cap 4
    return presets


PRESETS = _load_presets()


def resolve_preset(name: str) -> tuple[list[str], str]:
    p = PRESETS[name]  # KeyError on unknown
    return list(p["panel"]), p["judge"]


def _openai_key() -> str:
    return os.environ.get("OPENAI_API_KEY", "")


def _anthropic_key() -> str:
    return os.environ.get("ANTHROPIC_API_KEY", "")


async def call_model(model_id: str, messages: list[dict], *, max_tokens: int,
                     timeout_s: float, client: httpx.AsyncClient) -> str:
    """One model's answer as text. Raises KeyError (unknown model) or
    httpx.HTTPError / RuntimeError on a bad response."""
    spec = PROVIDER_REGISTRY[model_id]  # KeyError = unknown
    if spec.provider == "openai":
        body = {"model": spec.api_model, "messages": messages}
        if spec.contract == "openai_new":
            body["max_completion_tokens"] = max_tokens
        else:
            body["max_tokens"] = max_tokens
            body["temperature"] = 0.7
        r = await client.post(f"{OPENAI_BASE}/chat/completions", json=body,
                              headers={"authorization": f"Bearer {_openai_key()}"},
                              timeout=timeout_s)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"] or ""
    # anthropic
    system = ""
    conv = []
    for m in messages:
        if m.get("role") == "system":
            system += (m.get("content") or "")
        else:
            conv.append({"role": m["role"], "content": m.get("content", "")})
    body = {"model": spec.api_model, "max_tokens": max_tokens, "messages": conv}
    if system:
        body["system"] = system
    r = await client.post(f"{ANTHROPIC_BASE}/messages", json=body,
                          headers={"x-api-key": _anthropic_key(),
                                   "anthropic-version": "2023-06-01"},
                          timeout=timeout_s)
    r.raise_for_status()
    parts = r.json().get("content", [])
    return "".join(p.get("text", "") for p in parts if p.get("type") == "text")
