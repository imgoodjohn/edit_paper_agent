"""ComprehensionAgent: produce a structured paper-understanding card.

Always run BEFORE the planner. The user reviews the card in the Web UI
and can correct any misreading via free-form text; that correction is
folded into the planner's input.
"""
from __future__ import annotations

from typing import Optional

from ..ir import DocumentTree
from ..llm import LLMClient, ModelTier
from .constraints import build_system_prompt
from .prompts import load_prompt
from .schema import ComprehensionCard


def _condense_paper(tree: DocumentTree, max_chars: int = 16000) -> str:
    """Pack title + abstract + every section heading + first paragraph into
    a single string under the budget."""
    parts: list[str] = []
    parts.append(f"# TITLE\n{tree.title}\n")
    if tree.abstract is not None:
        parts.append(f"# ABSTRACT\n{tree.abstract.text}\n")
    for sec in tree.sections:
        parts.append(f"## SECTION [{sec.level}] {sec.title} (id={sec.id})")
        if sec.paragraphs:
            parts.append(sec.paragraphs[0].text[:1200])
        for sub in sec.children:
            parts.append(f"### SUB [{sub.level}] {sub.title} (id={sub.id})")
            if sub.paragraphs:
                parts.append(sub.paragraphs[0].text[:600])
    blob = "\n\n".join(parts)
    if len(blob) > max_chars:
        blob = blob[:max_chars] + "\n\n[... truncated ...]"
    return blob


class ComprehensionAgent:
    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def run(
        self,
        tree: DocumentTree,
        tier: ModelTier = ModelTier.SMART,
        model: Optional[str] = None,
    ) -> ComprehensionCard:
        system = build_system_prompt(load_prompt("comprehension"))
        user = (
            "Here is the paper digest you must understand. Return JSON only.\n\n"
            + _condense_paper(tree)
        )
        data = self.llm.complete_json(
            system=system, user=user, tier=tier, temperature=0.1, max_tokens=4096,
            model=model,
        )
        card = ComprehensionCard.from_dict(data)
        return card
