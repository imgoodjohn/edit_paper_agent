"""Journal-fit predictor.

Two roles:
  1. The user can ask "which journal best fits my paper?" -> returns ranked list.
  2. If the user has not picked a journal, the orchestrator can auto-pick the
     top result and use it as the target for PlannerAgent.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Optional

from ..agents.comprehension_agent import _condense_paper
from ..agents.constraints import build_system_prompt
from ..agents.prompts import load_prompt
from ..agents.schema import ComprehensionCard
from ..ir import DocumentTree
from ..llm import LLMClient, ModelTier

from ..skills import JournalSkill, SkillLoader


@dataclass
class JournalRanking:
    ranked: list[dict] = field(default_factory=list)
    top_pick: str = ""
    rationale: str = ""
    raw_response: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


_SPLIT_RE = re.compile(r"\W+")


def _keywords(text: str) -> set[str]:
    return {w.lower() for w in _SPLIT_RE.split(text) if len(w) > 3}


def _prefilter_candidates(
    skills: list[JournalSkill],
    comprehension: Optional[ComprehensionCard],
    tree: DocumentTree,
    top_k: int = 10,
) -> list[JournalSkill]:
    """Keyword-overlap pre-filter: keep only the top_k most relevant journals."""
    if len(skills) <= top_k:
        return skills
    paper_words: set[str] = _keywords(tree.title or "")
    if comprehension:
        for txt in [
            comprehension.field or "",
            comprehension.subfield or "",
            comprehension.one_line_summary or "",
            *list(comprehension.key_claims or []),
        ]:
            paper_words |= _keywords(txt)

    def _score(skill: JournalSkill) -> int:
        j_words: set[str] = set()
        for disc in skill.raw.get("journal", {}).get("discipline", []):
            j_words |= _keywords(disc)
        for kw in skill.raw.get("scope", {}).get("keywords", []):
            j_words |= _keywords(kw)
        return len(paper_words & j_words)

    return sorted(skills, key=_score, reverse=True)[:top_k]


def _format_candidates(skills: list[JournalSkill]) -> str:
    parts = ["# Candidate journals"]
    for s in skills:
        j = s.raw.get("journal", {})
        scope = s.raw.get("scope", {})
        disciplines = ", ".join(j.get("discipline", []))
        keywords = ", ".join(scope.get("keywords", [])[:10])
        desc = (scope.get("description") or "").strip().replace("\n", " ")[:120]
        parts.append(
            f"- key={s.key} | name={s.name} | disciplines=[{disciplines}] | "
            f"keywords=[{keywords}] | scope={desc}"
        )
    return "\n".join(parts)


class JournalPredictor:
    def __init__(self, llm: LLMClient, loader: Optional[SkillLoader] = None) -> None:
        self.llm = llm
        self.loader = loader or SkillLoader()

    def rank(
        self,
        tree: DocumentTree,
        comprehension: Optional[ComprehensionCard] = None,
        candidates: Optional[list[str]] = None,
        tier: ModelTier = ModelTier.SMART,
        top_k: int = 10,
    ) -> JournalRanking:
        # Load the candidate skills then pre-filter to top_k
        keys = candidates or self.loader.list_skills()
        skills = [self.loader.load(k) for k in keys]
        if not skills:
            return JournalRanking()
        skills = _prefilter_candidates(skills, comprehension, tree, top_k=top_k)

        system = build_system_prompt(load_prompt("journal_predictor"))
        digest_parts = [_condense_paper(tree, max_chars=6000)]
        if comprehension is not None:
            digest_parts.insert(
                0,
                "# Pre-computed paper understanding\n"
                + (comprehension.one_line_summary or "")
                + "\nKey claims:\n- "
                + "\n- ".join(comprehension.key_claims),
            )
        user = "\n\n".join(
            [
                "# Paper digest",
                "\n\n".join(digest_parts),
                _format_candidates(skills),
                "Return ONLY raw JSON — no markdown, no ```json fences.",
            ]
        )
        data = self.llm.complete_json(
            system=system, user=user, tier=tier, temperature=0.2, max_tokens=1024
        )
        return JournalRanking(
            ranked=list(data.get("ranked", [])),
            top_pick=data.get("top_pick", ""),
            rationale=data.get("rationale", ""),
            raw_response="",
        )
