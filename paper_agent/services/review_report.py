"""Full reviewer report.

Outputs holistic judgment, scores per criterion, recommended decision,
suggested experiments to strengthen claims, and a draft decision letter.
The token-frugal design: ONE call produces all of this.

The `experiments_to_strengthen` field is the place where the user is
prompted (per request) about whether they need to do more experiments.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional

from ..agents.comprehension_agent import _condense_paper
from ..agents.constraints import build_system_prompt
from ..agents.prompts import load_prompt
from ..agents.schema import ComprehensionCard
from ..ir import DocumentTree
from ..llm import LLMClient, ModelTier

from ..skills import JournalSkill


@dataclass
class ReviewReport:
    summary: str = ""
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    scores: dict = field(default_factory=dict)         # novelty, technical_soundness, ...
    recommendation: str = ""                            # accept | minor_revision | major_revision | reject
    experiments_to_strengthen: list[dict] = field(default_factory=list)
    compliance_check: list[dict] = field(default_factory=list)
    decision_letter_draft: str = ""
    raw_response: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def needs_experiments(self) -> bool:
        return any(
            (e.get("priority") in ("high", "medium"))
            for e in self.experiments_to_strengthen
        )


def _format_skill_rules(skill: JournalSkill) -> str:
    out = [f"# Target journal: {skill.name}"]
    rules = (
        list(skill.compliance_rules)
        + list(skill.structure_rules)
        + list(skill.content_rules)
    )
    for r in rules[:25]:  # token cap
        out.append(f"- {r}")
    return "\n".join(out)


class ReviewReporter:
    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def report(
        self,
        tree: DocumentTree,
        skill: JournalSkill,
        comprehension: Optional[ComprehensionCard] = None,
        language: str = "en",
        tier: ModelTier = ModelTier.DEEP,
    ) -> ReviewReport:
        system = build_system_prompt(
            load_prompt("review_report"),
            extra_rules=f"Write all prose fields (summary, decision_letter_draft) in {language}.",
        )
        digest = _condense_paper(tree, max_chars=14000)
        comp_blob = ""
        if comprehension is not None:
            comp_blob = (
                "# Author-confirmed understanding\n"
                + (comprehension.one_line_summary or "")
                + "\nClaims: "
                + "; ".join(comprehension.key_claims[:6])
                + "\n"
            )
        user = "\n\n".join(
            [
                _format_skill_rules(skill),
                comp_blob,
                "# Paper digest",
                digest,
                "Return JSON only.",
            ]
        )
        data = self.llm.complete_json(
            system=system, user=user, tier=tier, temperature=0.2, max_tokens=8192
        )
        rep = ReviewReport(
            summary=data.get("summary", ""),
            strengths=list(data.get("strengths", [])),
            weaknesses=list(data.get("weaknesses", [])),
            scores=dict(data.get("scores", {})),
            recommendation=data.get("recommendation", ""),
            experiments_to_strengthen=list(data.get("experiments_to_strengthen", [])),
            compliance_check=list(data.get("compliance_check", [])),
            decision_letter_draft=data.get("decision_letter_draft", ""),
            raw_response="",
        )
        return rep
