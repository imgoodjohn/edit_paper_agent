"""Grammar auto-fix.

A thin convenience wrapper that produces a single batch of language-only
suggestions covering the whole document, using the existing EditorAgent
with a synthetic TodoItem. The Web UI can pre-check "accept all" for
suggestions where:
  * severity == "info"
  * flag_for_user is False
  * numeric_warnings is empty
  * category == "language"

The user can untick any item before applying. This is the path that
satisfies "auto-fix grammar" without bypassing the safety checks.
"""
from __future__ import annotations

from typing import Optional

from ..agents.editor_agent import EditorAgent, EditorRunResult
from ..agents.schema import Suggestion, TodoItem
from ..ir import DocumentTree
from ..llm import LLMClient, ModelTier
from ..skills import JournalSkill


_SYNTHETIC_TODO_DESCRIPTION = (
    "Auto-fix grammar, punctuation, tense consistency, and remove AI-flavored "
    "openers. Do NOT make structural or content changes. Do NOT touch any "
    "numbers, citations, or `\\ref/\\label` keys. Prefer the smallest possible "
    "diff per fix; many one-word fixes are better than one paragraph rewrite."
)


class GrammarAutoFixer:
    def __init__(self, llm: LLMClient, editor: Optional[EditorAgent] = None) -> None:
        self.llm = llm
        self.editor = editor or EditorAgent(llm)

    def run(
        self,
        tree: DocumentTree,
        skill: JournalSkill,
        compact_memory: str = "",
        language: str = "en",
        tier: ModelTier = ModelTier.FAST,
    ) -> EditorRunResult:
        synth = TodoItem(
            id="auto-grammar",
            category="language",
            priority="medium",
            title="Auto-fix grammar and remove AI-flavor openers",
            description=_SYNTHETIC_TODO_DESCRIPTION,
            target_section_ids=[],
            target_paragraph_ids=[],
            expected_outcome="Cleaner prose; no semantic or numeric changes.",
        )
        # Inject language preference for rationales via compact_memory channel
        # (free-form prefix). This avoids changing EditorAgent's signature.
        memory = (compact_memory + "\n\n" if compact_memory else "") + (
            f"User preference: produce `rationale` in {language}."
        )
        return self.editor.run(synth, tree, skill, compact_memory=memory, tier=tier)


def is_auto_acceptable(s: Suggestion) -> bool:
    """Predicate the UI can use to pre-check 'accept' boxes."""
    return (
        s.category == "language"
        and s.severity == "info"
        and not s.flag_for_user
        and not s.numeric_warnings
    )
