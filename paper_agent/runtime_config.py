"""Runtime LLM configuration -- file-persisted, hot-reloadable.

The Web UI lets the user change the API endpoint, key, and tier->model
mapping without restarting the backend. Values are persisted to
`<repo>/config.json`. On every read we re-load from disk so the running
LLMClient sees fresh values.

API keys are NEVER returned to the UI in plain text. `to_public_dict()`
masks them as ``sk-...****...AB`` (first 4 / last 2 chars visible).

Precedence
----------
1. config.json (if present)
2. Environment variables (PAPER_AGENT_API_KEY / BASE_URL / FAST/SMART/DEEP_MODEL)
3. Hard-coded fallbacks (matches the original main.py).
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional


CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.json"


_DEFAULT_API_KEY = "sk-EFqIofpeD97Am9TkEsVHmQ"
_DEFAULT_BASE_URL = "https://hnd1.aihub.zeabur.ai/"


@dataclass
class RuntimeLLMConfig:
    api_key: str = ""
    base_url: str = ""
    fast_model: str = ""
    smart_model: str = ""
    deep_model: str = ""

    def merged_with_env(self) -> "RuntimeLLMConfig":
        # Models intentionally have NO hardcoded defaults: the operator must
        # pick one of the IDs returned by `/v1/models` (surfaced in Settings).
        # If the env var is set we honour it, otherwise the field stays blank
        # and the agents will refuse to run with a clear error message.
        return RuntimeLLMConfig(
            api_key=self.api_key
            or os.environ.get("PAPER_AGENT_API_KEY", _DEFAULT_API_KEY),
            base_url=self.base_url
            or os.environ.get("PAPER_AGENT_BASE_URL", _DEFAULT_BASE_URL),
            fast_model=self.fast_model or os.environ.get("PAPER_AGENT_FAST_MODEL", ""),
            smart_model=self.smart_model or os.environ.get("PAPER_AGENT_SMART_MODEL", ""),
            deep_model=self.deep_model or os.environ.get("PAPER_AGENT_DEEP_MODEL", ""),
        )

    def to_public_dict(self) -> dict:
        merged = self.merged_with_env()
        return {
            "api_key_masked": _mask(merged.api_key),
            "api_key_set": bool(merged.api_key),
            "base_url": merged.base_url,
            "fast_model": merged.fast_model,
            "smart_model": merged.smart_model,
            "deep_model": merged.deep_model,
        }


_LOCK = threading.RLock()


def _mask(s: str) -> str:
    if not s:
        return ""
    if len(s) <= 8:
        return "***"
    return f"{s[:4]}...{'*' * 4}...{s[-2:]}"


def load() -> RuntimeLLMConfig:
    """Read config.json (if exists) into a RuntimeLLMConfig."""
    with _LOCK:
        if not CONFIG_PATH.exists():
            return RuntimeLLMConfig()
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return RuntimeLLMConfig()
        return RuntimeLLMConfig(
            api_key=str(data.get("api_key", "")),
            base_url=str(data.get("base_url", "")),
            fast_model=str(data.get("fast_model", "")),
            smart_model=str(data.get("smart_model", "")),
            deep_model=str(data.get("deep_model", "")),
        )


def save(cfg: RuntimeLLMConfig) -> None:
    with _LOCK:
        CONFIG_PATH.write_text(
            json.dumps(asdict(cfg), ensure_ascii=False, indent=2), encoding="utf-8"
        )


def update(patch: dict) -> RuntimeLLMConfig:
    """Merge patch into existing config and persist.

    Empty-string values are treated as "do not change" so the UI can leave
    the API key field blank to preserve the existing key.
    Pass the literal string ``"__clear__"`` to wipe a field back to
    env/default.
    """
    with _LOCK:
        cur = load()
        for k in ("api_key", "base_url", "fast_model", "smart_model", "deep_model"):
            if k not in patch:
                continue
            v = patch[k]
            if v == "__clear__":
                setattr(cur, k, "")
            elif isinstance(v, str) and v != "":
                setattr(cur, k, v)
        save(cur)
        return cur


def merged() -> RuntimeLLMConfig:
    """Convenience: load + apply env fallback. This is what the LLMClient uses."""
    return load().merged_with_env()
