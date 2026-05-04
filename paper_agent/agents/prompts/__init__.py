"""Prompt templates loaded from .md files in this directory.

Keeping prompts as separate files (not Python string literals) makes them
diffable, easier to iterate on, and lets non-engineers tune them.
"""
from __future__ import annotations

from pathlib import Path

_HERE = Path(__file__).resolve().parent


def load_prompt(name: str) -> str:
    """Load a prompt by name (without .md extension)."""
    path = _HERE / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt not found: {path}")
    return path.read_text(encoding="utf-8").strip()


__all__ = ["load_prompt"]
