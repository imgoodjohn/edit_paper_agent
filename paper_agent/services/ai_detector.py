"""AI-writing-rate detector.

Per user spec: this score is **stateless / no-memory**. We never write the
result into the Session memory or the decision log, and we never accept a
prior result as input. Each call recomputes from scratch over the supplied
text. The result is returned to the UI as a one-shot artifact.

The function refuses to take a Session argument deliberately, to make
the no-mem invariant impossible to violate by accident.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional

from ..agents.constraints import build_system_prompt
from ..agents.prompts import load_prompt
from ..ir import DocumentTree
from ..llm import LLMClient, ModelTier



@dataclass
class AIDetectionResult:
    ai_likelihood: int = 0       # 0-100
    verdict: str = "human"       # human | mixed | likely_ai
    top_signals: list[str] = field(default_factory=list)
    examples: list[dict] = field(default_factory=list)
    advice: str = ""
    raw_response: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _gather_text(tree: DocumentTree, max_chars: int = 12000) -> str:
    """Concatenate body paragraphs (skip captions, abstract handled separately).

    We deliberately drop the abstract because abstracts are the most
    AI-rewritten section and would skew the score upward; the user wants
    a paper-level estimate.
    """
    chunks = []
    if tree.abstract is not None:
        chunks.append("[ABSTRACT] " + tree.abstract.text)
    for sec in tree.sections:
        for sub in sec.walk():
            for p in sub.paragraphs:
                if p.kind == "body":
                    chunks.append(p.text)
    blob = "\n\n".join(chunks)
    if len(blob) > max_chars:
        # take a sampled window: head + middle + tail to capture variety
        third = max_chars // 3
        blob = blob[:third] + "\n\n[...]\n\n" + blob[len(blob) // 2 - third // 2 : len(blob) // 2 + third // 2] + "\n\n[...]\n\n" + blob[-third:]
    return blob


class AIDetector:
    """Stateless detector. Do not pass Session-derived state in here."""

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm
        # Explicitly: no cache, no history, no session reference.

    def detect(
        self,
        tree: DocumentTree,
        tier: ModelTier = ModelTier.SMART,
        language: str = "en",
    ) -> AIDetectionResult:
        system = build_system_prompt(
            load_prompt("ai_detector"),
            extra_rules=f"Write `advice` and `examples[].why` in {language}.",
        )
        user = (
            "# Paper text (sampled if long)\n\n"
            + _gather_text(tree)
            + "\n\nReturn JSON only."
        )
        data = self.llm.complete_json(
            system=system, user=user, tier=tier, temperature=0.2, max_tokens=3000
        )
        return AIDetectionResult(
            ai_likelihood=int(data.get("ai_likelihood", 0)),
            verdict=data.get("verdict", "human"),
            top_signals=list(data.get("top_signals", [])),
            examples=list(data.get("examples", [])),
            advice=data.get("advice", ""),
            raw_response="",
        )
