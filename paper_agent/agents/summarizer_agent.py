"""SummarizerAgent: compact the decision log into CompactMemory.

Triggered manually from the Web UI ("Compact session memory" button) or
automatically when the decision log exceeds a token threshold. Writes
the result back into Session.memory and updates `last_compacted_log_index`
so subsequent runs only summarize new entries.
"""
from __future__ import annotations

import json
from typing import Optional

from ..llm import LLMClient, ModelTier

from ..session import CompactMemory, Session
from .constraints import build_system_prompt
from .prompts import load_prompt


def _format_log_window(session: Session) -> str:
    start = session.memory.last_compacted_log_index
    new_entries = session.decision_log[start:]
    if not new_entries:
        return ""
    blob = []
    mem = session.memory
    if mem.compact_summary:
        blob.append("# Previous summary")
        blob.append(mem.compact_summary)
    if mem.rejected_patterns:
        blob.append("# Rejected patterns")
        for rp in mem.rejected_patterns:
            blob.append(f"- {rp.get('pattern','')}: {rp.get('reason','')}")
    if mem.consistency_notes:
        blob.append("# Consistency rules")
        for cn in mem.consistency_notes:
            blob.append(f"- {cn.get('term','')}: {cn.get('rule','')}")
    blob.append(f"# New entries ({len(new_entries)})")
    for e in new_entries:
        blob.append(json.dumps({"kind": e.kind, "payload": e.payload}, ensure_ascii=False))
    if session.plan is not None:
        blob.append("# TODO statuses")
        for t in session.plan.todos:
            blob.append(f"- [{t.status}] {t.title}")
    return "\n".join(blob)


class SummarizerAgent:
    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def compact(
        self, session: Session, tier: ModelTier = ModelTier.FAST
    ) -> CompactMemory:
        body = _format_log_window(session)
        if not body:
            return session.memory

        n_new = len(session.decision_log) - session.memory.last_compacted_log_index
        system = build_system_prompt(load_prompt("summarizer"))
        data = self.llm.complete_json(
            system=system, user=body, tier=tier, temperature=0.1, max_tokens=2048
        )

        new_mem = CompactMemory.from_dict(data)
        new_mem.last_compacted_log_index = len(session.decision_log)
        session.memory = new_mem
        return new_mem, n_new
