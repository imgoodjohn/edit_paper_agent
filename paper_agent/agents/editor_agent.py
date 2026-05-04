"""EditorAgent: executes ONE TodoItem and returns Suggestions.

Operates per-paragraph for the paragraphs targeted by the todo (or, if
none specified, the full set of body paragraphs in the targeted sections).
Every produced suggestion is automatically run through the NumberGuard;
if numbers/citations changed, `flag_for_user` is forced to True.

The agent receives a *compact memory* string so it stays consistent with
prior user decisions across a long session.
"""
from __future__ import annotations

from typing import Callable, Iterable, Optional
from dataclasses import dataclass

from ..guardrails import NumberGuard
from ..ir import DocumentTree, Paragraph
from ..llm import LLMClient, ModelTier

from ..skills import JournalSkill
from .constraints import build_system_prompt
from .prompts import load_prompt
from .schema import Suggestion, TodoItem, _uid


# How many paragraphs to send the model in a single request.
# Trade-off: bigger context = better consistency, but more tokens / slower.
DEFAULT_BATCH = 4


@dataclass
class EditorRunResult:
    todo_id: str
    suggestions: list[Suggestion]
    notes: list[str]


class EditorAgent:
    def __init__(self, llm: LLMClient, guard: Optional[NumberGuard] = None) -> None:
        self.llm = llm
        self.guard = guard or NumberGuard()

    # ----------------------------------------------------------- public API

    def run(
        self,
        todo: TodoItem,
        tree: DocumentTree,
        skill: JournalSkill,
        compact_memory: str = "",
        plan_summary: str = "",
        tier: ModelTier = ModelTier.SMART,
        batch_size: int = DEFAULT_BATCH,
        language: str = "en",
        model: Optional[str] = None,
        on_batch: Optional[
            Callable[[int, int, int, list[Suggestion]], None]
        ] = None,
    ) -> EditorRunResult:
        """Run the editor agent for one TODO.

        `on_batch(batch_idx, batch_total, paragraphs_done, batch_suggestions)`
        is called after every batch so the orchestrator can surface progress
        through SSE without coupling to FastAPI here.
        """
        if todo.needs_human:
            return EditorRunResult(
                suggestions=[],
                notes="Skipped: this task requires human action (experiments / data) "
                      "and cannot be auto-edited.",
                todo_id=todo.id,
            )
        paragraphs = self._target_paragraphs(todo, tree)
        batches = list(_chunks(paragraphs, batch_size))
        out: list[Suggestion] = []
        notes: list[str] = []
        done_paras = 0
        total_batches = max(1, len(batches))
        for i, batch in enumerate(batches):
            try:
                sugs, note = self._run_batch(
                    todo, batch, skill, compact_memory, plan_summary, tier, language, model
                )
            except Exception as e:
                notes.append(f"[batch error] {e}")
                if on_batch is not None:
                    try:
                        on_batch(i + 1, total_batches, done_paras, [])
                    except Exception:
                        pass
                done_paras += len(batch)
                continue
            out.extend(sugs)
            done_paras += len(batch)
            if note:
                notes.append(note)
            if on_batch is not None:
                try:
                    on_batch(i + 1, total_batches, done_paras, sugs)
                except Exception:
                    pass
        return EditorRunResult(todo_id=todo.id, suggestions=out, notes=notes)

    # --------------------------------------------------------------- helpers

    def _target_paragraphs(self, todo: TodoItem, tree: DocumentTree) -> list[Paragraph]:
        if todo.target_paragraph_ids:
            paras: list[Paragraph] = []
            for pid in todo.target_paragraph_ids:
                p = tree.find_paragraph(pid)
                if p is not None:
                    paras.append(p)
            if paras:
                return paras
        if todo.target_section_ids:
            paras = []
            for sid in todo.target_section_ids:
                sec = tree.find_section(sid)
                if sec is not None:
                    paras.extend(sec.all_paragraphs())
            if paras:
                return paras
        # Fall back: whole-document scope (rare; only for global todos).
        return list(tree.all_paragraphs())

    def _run_batch(
        self,
        todo: TodoItem,
        batch: list[Paragraph],
        skill: JournalSkill,
        compact_memory: str,
        plan_summary: str,
        tier: ModelTier,
        language: str = "en",
        model: Optional[str] = None,
    ) -> tuple[list[Suggestion], str]:
        extra = f"Write the `rationale` field in {language}."
        system = build_system_prompt(load_prompt("editor"), extra_rules=extra)
        user = self._build_user_prompt(todo, batch, skill, compact_memory, plan_summary)
        data = self.llm.complete_json(
            system=system, user=user, tier=tier, temperature=0.15, max_tokens=8192,
            model=model,
        )

        suggestions: list[Suggestion] = []
        para_index = {p.id: p for p in batch}
        for s in data.get("suggestions", []):
            pid = s.get("paragraph_id", "")
            paragraph = para_index.get(pid)
            if paragraph is None:
                # model fabricated an id; skip
                continue
            before = s.get("before", "")
            after = s.get("after", "")
            if not before or before not in paragraph.text:
                # substring fidelity violated; skip rather than misapply
                continue
            sug = Suggestion(
                id=_uid("sug"),
                todo_id=todo.id,
                paragraph_id=pid,
                section_id=paragraph.metadata.get("section_id", ""),
                category=s.get("category", todo.category),
                severity=s.get("severity", "info"),
                before=before,
                after=after,
                rationale=s.get("rationale", ""),
                flag_for_user=bool(s.get("flag_for_user", False)),
            )
            # Always run guard, regardless of what the model claimed.
            report = self.guard.check(pid, before, after)
            if report.has_changes:
                sug.numeric_warnings = [c.to_dict() for c in report.changes]
                if report.critical():
                    sug.flag_for_user = True
                    if sug.severity == "info":
                        sug.severity = "warning"
            suggestions.append(sug)

        return suggestions, data.get("notes", "")

    def _build_user_prompt(
        self,
        todo: TodoItem,
        batch: list[Paragraph],
        skill: JournalSkill,
        compact_memory: str,
        plan_summary: str = "",
    ) -> str:
        parts: list[str] = []
        if plan_summary.strip():
            parts.append("# Revision plan (overall context)")
            parts.append(plan_summary.strip())
        parts.append("# Current TODO")
        parts.append(
            f"id: {todo.id}\n"
            f"category: {todo.category}\n"
            f"priority: {todo.priority}\n"
            f"title: {todo.title}\n"
            f"description: {todo.description}\n"
            f"expected_outcome: {todo.expected_outcome}"
        )

        # Journal rules relevant to this category
        relevant = self._rules_for_category(skill, todo.category)
        if relevant:
            parts.append("# Journal rules relevant to this todo")
            for r in relevant:
                parts.append(f"- {r}")

        if compact_memory.strip():
            parts.append("# Session memory (decisions so far -- stay consistent)")
            parts.append(compact_memory.strip())

        parts.append("# Paragraphs to review")
        for p in batch:
            parts.append(f"--- paragraph_id: {p.id} (kind={p.kind}) ---")
            parts.append(p.text)

        parts.append(
            "Return JSON only with the schema described in your system prompt. "
            "Output `before` substrings must appear character-for-character in the "
            "paragraph above whose id you reference."
        )
        return "\n\n".join(parts)

    @staticmethod
    def _rules_for_category(skill: JournalSkill, category: str) -> list[str]:
        # Always include compliance rules; add the specific category as well.
        rules = list(skill.compliance_rules)
        cat_to_attr = {
            "structure": skill.structure_rules,
            "content": skill.content_rules,
            "compliance": [],  # already added
            "language": skill.language_rules,
            "consistency": skill.language_rules,
            "figures_tables": skill.structure_rules,
            "references": skill.compliance_rules,
        }
        rules.extend(cat_to_attr.get(category, []))
        # de-dup, preserve order
        seen = set()
        out = []
        for r in rules:
            if r not in seen:
                seen.add(r)
                out.append(r)
        return out


def _chunks(items: list, n: int):
    for i in range(0, len(items), n):
        yield items[i : i + n]
