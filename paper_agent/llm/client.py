"""LLM client wrapper.

Goals
-----
* Single class used by every agent. Each call specifies a `tier`
  (FAST / SMART / DEEP), which maps to a concrete model. Different
  pipeline stages can pick different tiers (per user spec: plan stage
  may use a stronger model than the editing stage).
* JSON-only output: agents are required to return structured data,
  so we strip code fences and parse with helpful error messages.
* Pluggable backend: defaults to OpenAI-compatible HTTP (matches the
  existing main.py + Zeabur proxy). The Anthropic-native SDK can be
  swapped in by changing `LLMConfig.backend`.
* Sync + async: agents call `.complete_json()` (sync) for simplicity;
  the orchestrator wraps batches in `asyncio.to_thread`.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

_LOG = logging.getLogger(__name__)


class ModelTier(str, Enum):
    FAST = "fast"     # short, high-volume calls (per-paragraph editing)
    SMART = "smart"   # default; comprehension, summarization
    DEEP = "deep"     # plan generation, deep reasoning


# Tier -> model id. Empty by default: the operator selects a real model
# from `/v1/models` via the Settings page (or sets the env vars). We never
# invent vendor-specific IDs because they will silently fail against the
# user's actual endpoint.
MODEL_PRESETS: dict[ModelTier, str] = {
    ModelTier.FAST: os.environ.get("PAPER_AGENT_FAST_MODEL", ""),
    ModelTier.SMART: os.environ.get("PAPER_AGENT_SMART_MODEL", ""),
    ModelTier.DEEP: os.environ.get("PAPER_AGENT_DEEP_MODEL", ""),
}


def _runtime_defaults() -> dict:
    """Pull current values from runtime_config (file -> env -> hardcoded)."""
    from .. import runtime_config  # local import to avoid cycle at module load

    cfg = runtime_config.merged()
    return {
        "api_key": cfg.api_key,
        "base_url": cfg.base_url,
        "presets": {
            ModelTier.FAST: cfg.fast_model,
            ModelTier.SMART: cfg.smart_model,
            ModelTier.DEEP: cfg.deep_model,
        },
    }


@dataclass
class LLMConfig:
    api_key: str = field(default_factory=lambda: _runtime_defaults()["api_key"])
    base_url: str = field(default_factory=lambda: _runtime_defaults()["base_url"])
    backend: str = "openai_compat"  # only one supported for now
    timeout: float = 180.0
    max_retries: int = 2
    presets: dict[ModelTier, str] = field(
        default_factory=lambda: _runtime_defaults()["presets"]
    )


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"```(?:json)?\s*(?P<body>.*?)```", re.DOTALL)


def _extract_json(text: str) -> Any:
    """Extract the first JSON object/array from a model response.

    Strategy: try a direct json.loads on the trimmed string; if that fails,
    look for a ```json fenced block; finally, try to find the first balanced
    {...} or [...] span.
    """
    s = text.strip()
    try:
        return json.loads(s)
    except Exception:
        pass

    m = _FENCE_RE.search(s)
    if m:
        body = m.group("body").strip()
        try:
            return json.loads(body)
        except Exception:
            s = body  # continue with the de-fenced body

    # Find the first balanced JSON value
    start_chars = ["{", "["]
    for i, ch in enumerate(s):
        if ch in start_chars:
            end = _balanced_end(s, i)
            if end is not None:
                try:
                    return json.loads(s[i : end + 1])
                except Exception:
                    continue
    raise ValueError(
        f"Could not parse JSON from model response. First 400 chars:\n{text[:400]}"
    )


def _no_system_msg_error(exc: Exception) -> bool:
    """True when the provider rejects system/developer role messages."""
    msg = str(exc).lower()
    return (
        "system and developer messages are not allowed" in msg
        or "system messages are not allowed" in msg
        or "developer messages are not allowed" in msg
        or ("system" in msg and "not allowed" in msg)
    )


def _balanced_end(s: str, start: int) -> Optional[int]:
    open_ch = s[start]
    close_ch = "}" if open_ch == "{" else "]"
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(s)):
        c = s[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return i
    return None


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class LLMClient:
    def __init__(self, config: Optional[LLMConfig] = None) -> None:
        self.config = config or LLMConfig()
        self._oai = None  # lazy

    def _client(self):
        if self._oai is None:
            import httpx
            from openai import OpenAI

            self._oai = OpenAI(
                api_key=self.config.api_key,
                base_url=self.config.base_url,
                timeout=self.config.timeout,
                max_retries=self.config.max_retries,
                # Bypass Windows system proxy (IDE may intercept outgoing HTTP)
                http_client=httpx.Client(trust_env=False),
            )
        return self._oai

    def model_for(self, tier: ModelTier) -> str:
        mid = self.config.presets.get(tier, "")
        if not mid:
            raise RuntimeError(
                f"No model configured for tier '{tier.value}'. Open Settings "
                f"and pick one from the auto-discovered list, or set the "
                f"PAPER_AGENT_{tier.value.upper()}_MODEL environment variable."
            )
        return mid

    # ----------------------------------------------------------- discovery

    def list_models(self) -> list[str]:
        """Return the set of model ids the backend reports as available.

        Tries the OpenAI-style `/v1/models` endpoint. Falls back to the
        configured presets if the endpoint is missing or unauthorized.
        """
        try:
            res = self._client().models.list()
            ids: list[str] = []
            for m in res.data:
                mid = getattr(m, "id", None)
                if isinstance(mid, str) and mid:
                    ids.append(mid)
            if ids:
                return sorted(set(ids))
        except Exception:
            pass
        # Fall back to whichever presets ARE configured (skip blanks).
        return sorted({m for m in self.config.presets.values() if m})

    # ------------------------------------------------------------------ chat

    def complete_text(
        self,
        *,
        system: str,
        user: str,
        tier: ModelTier = ModelTier.SMART,
        temperature: float = 0.2,
        max_tokens: int = 8192,
        model: Optional[str] = None,
    ) -> str:
        model_id = model or self.model_for(tier)
        try:
            resp = self._client().chat.completions.create(
                model=model_id,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return resp.choices[0].message.content or ""
        except Exception as exc:
            if _no_system_msg_error(exc):
                # Provider does not accept system-role messages — merge into user turn
                _LOG.warning(
                    "Provider rejected system message (%s); retrying with merged user prompt.",
                    exc,
                )
                merged = f"<instructions>\n{system}\n</instructions>\n\n{user}"
                resp = self._client().chat.completions.create(
                    model=model_id,
                    messages=[{"role": "user", "content": merged}],
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                return resp.choices[0].message.content or ""
            raise

    def complete_messages(
        self,
        *,
        messages: list[dict],
        tier: ModelTier = ModelTier.SMART,
        temperature: float = 0.1,
        max_tokens: int = 4096,
        model: Optional[str] = None,
    ) -> str:
        """Multi-turn chat: accepts a pre-built messages list."""
        model_id = model or self.model_for(tier)
        try:
            resp = self._client().chat.completions.create(
                model=model_id,
                messages=messages,  # type: ignore[arg-type]
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return resp.choices[0].message.content or ""
        except Exception as exc:
            if _no_system_msg_error(exc):
                # Merge system messages into the first user turn
                _LOG.warning(
                    "Provider rejected system message in multi-turn; merging system into user turn."
                )
                merged: list[dict] = []
                sys_parts: list[str] = []
                for m in messages:
                    if m.get("role") == "system":
                        sys_parts.append(m["content"])
                    else:
                        merged.append(m)
                if sys_parts and merged:
                    prefix = "<instructions>\n" + "\n".join(sys_parts) + "\n</instructions>\n\n"
                    merged[0] = {**merged[0], "content": prefix + merged[0]["content"]}
                resp = self._client().chat.completions.create(
                    model=model_id,
                    messages=merged,  # type: ignore[arg-type]
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                return resp.choices[0].message.content or ""
            raise

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        tier: ModelTier = ModelTier.SMART,
        temperature: float = 0.1,
        max_tokens: int = 8192,
        model: Optional[str] = None,
    ) -> Any:
        """Like complete_text but parses the response as JSON.

        If the first response can't be parsed as JSON, retries once with an
        explicit "JSON only" instruction appended to the user prompt.
        """
        text = self.complete_text(
            system=system,
            user=user,
            tier=tier,
            temperature=temperature,
            max_tokens=max_tokens,
            model=model,
        )
        def _unwrap(v: Any) -> Any:
            """If model returns [{...}] instead of {...}, unwrap the first element."""
            if isinstance(v, list) and len(v) == 1 and isinstance(v[0], dict):
                _LOG.warning("Model returned a single-element array; unwrapping to dict.")
                return v[0]
            return v

        try:
            return _unwrap(_extract_json(text))
        except ValueError:
            _LOG.warning(
                "JSON parse failed on first attempt (first 200 chars: %r); retrying with explicit JSON instruction.",
                text[:200],
            )
            retry_user = (
                user
                + "\n\nIMPORTANT: Your response MUST be valid JSON only. "
                  "Do NOT include any explanation, markdown, or other text — "
                  "output ONLY the raw JSON object as specified."
            )
            text2 = self.complete_text(
                system=system,
                user=retry_user,
                tier=tier,
                temperature=0.0,
                max_tokens=max_tokens,
                model=model,
            )
            return _unwrap(_extract_json(text2))
