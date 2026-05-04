"""Journal skill (YAML) loader.

Looks in two locations (in order):
  1. <repo>/skills/journals/*.yaml   (canonical, per design doc)
  2. <repo>/*.yaml                   (legacy / current state)

A skill is exposed as a JournalSkill dataclass with the four rule lists
that map directly onto the four sub-agents.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class JournalSkill:
    key: str                     # filename stem, e.g. "nature"
    name: str                    # human name, e.g. "Nature"
    raw: dict = field(default_factory=dict)

    @property
    def structure_rules(self) -> list[str]:
        return list(self.raw.get("agents", {}).get("structure_rules", []))

    @property
    def content_rules(self) -> list[str]:
        return list(self.raw.get("agents", {}).get("content_rules", []))

    @property
    def compliance_rules(self) -> list[str]:
        return list(self.raw.get("agents", {}).get("compliance_rules", []))

    @property
    def language_rules(self) -> list[str]:
        return list(self.raw.get("agents", {}).get("language_rules", []))

    def article_types(self) -> list[dict]:
        return list(self.raw.get("article_types", []))

    def required_sections(self) -> list[str]:
        return list(self.raw.get("sections", {}).get("required", []))


class SkillLoader:
    def __init__(self, search_paths: Optional[list[Path]] = None) -> None:
        if search_paths is None:
            here = Path(__file__).resolve().parents[2]
            search_paths = [
                here / "skills",          # category subfolders (rglob'd)
                here / "skills" / "journals",  # legacy flat layout
                here,                     # repo-root yaml files
            ]
        self.search_paths = [p for p in search_paths if p.exists()]
        self._cache: dict[str, JournalSkill] = {}
        # Build a key→path index once at construction time so list/load are O(1).
        self._index: dict[str, Path] = {}
        self._build_index()

    def _build_index(self) -> None:
        for d in self.search_paths:
            for f in d.rglob("*.yaml"):
                if f.stem not in self._index:
                    self._index[f.stem] = f

    # --------------------------------------------------------------- discover

    def list_skills(self) -> list[str]:
        return sorted(self._index)

    # -------------------------------------------------------------- load one

    def load(self, key: str) -> JournalSkill:
        if key in self._cache:
            return self._cache[key]
        path = self._index.get(key)
        if path is None:
            raise FileNotFoundError(
                f"Journal skill '{key}' not found. Available: {self.list_skills()}"
            )
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        name = data.get("journal", {}).get("name", key)
        skill = JournalSkill(key=key, name=name, raw=data)
        self._cache[key] = skill
        return skill

    def _find(self, key: str) -> Optional[Path]:
        return self._index.get(key)

    def load_all(self) -> list[JournalSkill]:
        return [self.load(k) for k in self.list_skills()]
