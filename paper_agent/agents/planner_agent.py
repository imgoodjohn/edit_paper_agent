"""PlannerAgent: generates the whole-paper revision plan + TODO list.

Uses the DEEP tier by default (per user spec: plan stage uses the strongest
model). Sees: the comprehension card (with user corrections), the paper
digest, the journal skill rules. Returns a Plan with prioritized todos.
"""
from __future__ import annotations

import json
from typing import Optional

from ..ir import DocumentTree
from ..llm import LLMClient, ModelTier

from ..skills import JournalSkill
from .comprehension_agent import _condense_paper
from .constraints import build_system_prompt
from .prompts import load_prompt
from .schema import ComprehensionCard, Plan, TodoItem


def _format_skill(skill: JournalSkill) -> str:
    parts = [f"# Target journal: {skill.name} (key={skill.key})"]
    if skill.required_sections():
        parts.append("Required sections: " + ", ".join(skill.required_sections()))
    if skill.article_types():
        parts.append("Article types & limits:")
        for t in skill.article_types():
            parts.append(
                f"  - {t.get('type')}: word_limit={t.get('word_limit')}, "
                f"abstract_limit={t.get('abstract_limit')}, "
                f"figures_max={t.get('figures_max')}, references_max={t.get('references_max')}"
            )
    for kind in ("structure_rules", "content_rules", "compliance_rules", "language_rules"):
        rules = getattr(skill, kind)
        if rules:
            parts.append(f"{kind}:")
            for r in rules:
                parts.append(f"  - {r}")
    return "\n".join(parts)


def _format_comprehension(card: ComprehensionCard, user_corrections: str = "") -> str:
    out = ["# Author-confirmed understanding of the paper", json.dumps(card.to_dict(), ensure_ascii=False, indent=2)]
    if user_corrections.strip():
        out.append("\n# User corrections to the above understanding")
        out.append(user_corrections.strip())
    return "\n".join(out)


def _format_toc(tree: DocumentTree) -> str:
    lines = ["# Table of contents (use these ids in target_section_ids)"]
    for entry in tree.toc():
        indent = "  " * (entry["level"] - 1)
        lines.append(f"{indent}- {entry['id']}  [{entry['level']}] {entry['title']}")
    return "\n".join(lines)


class PlannerAgent:
    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def run(
        self,
        tree: DocumentTree,
        skill: JournalSkill,
        comprehension: ComprehensionCard,
        user_corrections: str = "",
        tier: ModelTier = ModelTier.DEEP,
        model: Optional[str] = None,
    ) -> Plan:
        system = build_system_prompt(load_prompt("planner"))
        user = "\n\n".join(
            [
                _format_skill(skill),
                _format_comprehension(comprehension, user_corrections),
                _format_toc(tree),
                "# Paper digest (truncated)",
                _condense_paper(tree, max_chars=12000),
                "Now produce the revision plan. Output ONLY raw JSON — no markdown, no ```json fences, no explanations.",
            ]
        )
        data = self.llm.complete_json(
            system=system, user=user, tier=tier, temperature=0.2, max_tokens=8192,
            model=model,
        )
        if isinstance(data, list):
            data = {"overall_strategy": "", "risks": [], "todos": data}
        elif not isinstance(data, dict):
            data = {}
        # ensure each todo has an id
        for i, t in enumerate(data.get("todos", [])):
            if not isinstance(t, dict):
                continue
            if not t.get("id"):
                t["id"] = f"todo-{i:02d}"
        plan = Plan.from_dict(data)
        plan.journal_target = skill.key
        plan.raw_response = ""
        return plan
