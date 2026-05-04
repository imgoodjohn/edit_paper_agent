"""End-to-end test of the agent pipeline with a stub LLM (no network).

We swap LLMClient.complete_text with a callable that returns hand-crafted
JSON payloads, then assert that:
  * ComprehensionAgent parses the card
  * PlannerAgent produces a Plan with todos
  * EditorAgent produces Suggestions, applies NumberGuard, drops fabricated
    paragraph_ids, drops suggestions whose `before` is not a substring
  * SummarizerAgent compacts the log
  * Session round-trips through to_dict / from_dict
"""
from __future__ import annotations

import json
import textwrap

import pytest

from paper_agent.agents import (
    ComprehensionAgent,
    EditorAgent,
    PlannerAgent,
    SummarizerAgent,
)
from paper_agent.agents.schema import Plan, Suggestion, TodoItem
from paper_agent.llm import LLMClient
from paper_agent.parsers import LaTeXParser
from paper_agent.session import Session
from paper_agent.skills import SkillLoader


SAMPLE_TEX = textwrap.dedent(r"""
    \title{Foo: A Method for Bar}
    \begin{document}
    \begin{abstract}
    We achieve 92.4\% accuracy on Libero benchmark, outperforming prior
    work~\cite{smith2023} by 4 points. Our approach is simple.
    \end{abstract}
    \section{Introduction}
    In recent years, robotics has progressed rapidly~\cite{jones2024}.
    However, existing methods suffer from issue X. We address this gap.

    \section{Method}
    We propose a velocity-field attention mechanism. It is simple and effective.
    \end{document}
""").strip()


class StubLLM:
    """Stub LLMClient that returns canned responses keyed by which prompt is sent."""

    def __init__(self, router):
        self.router = router  # callable(system, user) -> str
        self.calls = []

    def complete_text(self, *, system, user, tier=None, **_):
        self.calls.append((system, user))
        return self.router(system, user)

    def complete_json(self, *, system, user, tier=None, **_):
        from paper_agent.llm.client import _extract_json

        return _extract_json(self.complete_text(system=system, user=user, tier=tier))

    def model_for(self, tier):
        return "stub-model"


@pytest.fixture
def tree():
    return LaTeXParser().parse(SAMPLE_TEX)


@pytest.fixture
def skill():
    return SkillLoader().load("nature")


def _route_factory(tree):
    """Return a router that picks a canned JSON based on which agent is calling."""

    body_para = next(p for p in tree.all_paragraphs() if p.kind == "body")

    comp_payload = {
        "title": "Foo: A Method for Bar",
        "one_line_summary": "Velocity-field attention for robot manipulation.",
        "field": "robot learning",
        "subfield": "vision-language-action",
        "problem": "Existing VLA methods treat all action steps uniformly.",
        "contributions": ["Velocity-field attention", "Improved Libero results"],
        "methods": ["velocity-field attention"],
        "key_claims": ["92.4% accuracy on Libero"],
        "datasets_or_benchmarks": ["Libero"],
        "limitations_self_stated": [],
        "confidence": 0.7,
        "open_questions": [],
    }

    plan_payload = {
        "overall_strategy": "Tighten language and remove AI-flavor openers.",
        "risks": ["Verify 92.4% appears consistently across abstract and tables."],
        "todos": [
            {
                "id": "todo-lang-01",
                "category": "language",
                "priority": "high",
                "title": "Remove AI-flavored openers",
                "description": "Delete 'In recent years' and similar empty openers in Introduction.",
                "target_section_ids": [tree.sections[0].id],
                "target_paragraph_ids": [],
                "expected_outcome": "Introduction starts with substantive content.",
            }
        ],
    }

    editor_payload = {
        "suggestions": [
            # Valid suggestion: remove "In recent years, " opener
            {
                "paragraph_id": body_para.id,
                "category": "language",
                "severity": "info",
                "before": "In recent years, robotics",
                "after": "Robotics",
                "rationale": "Removes AI-flavored opener while preserving meaning.",
                "flag_for_user": False,
            },
            # Invalid: paragraph_id fabricated -> should be dropped
            {
                "paragraph_id": "para-fake-xxx",
                "category": "language",
                "severity": "info",
                "before": "anything",
                "after": "anything else",
                "rationale": "ghost",
                "flag_for_user": False,
            },
            # Invalid: `before` not a substring -> should be dropped
            {
                "paragraph_id": body_para.id,
                "category": "language",
                "severity": "info",
                "before": "this string is definitely not in the paragraph",
                "after": "replacement",
                "rationale": "phantom edit",
                "flag_for_user": False,
            },
            # Numeric mutation: model claims flag_for_user=False; guard MUST flip it.
            {
                "paragraph_id": body_para.id,
                "category": "language",
                "severity": "info",
                "before": "issue X",
                "after": "issue 5",
                "rationale": "(intentionally bad: introduces a number)",
                "flag_for_user": False,
            },
        ],
        "notes": "two valid edits identified",
    }

    summ_payload = {
        "compact_summary": "You ran the planner; the editor produced one accepted edit.",
        "user_preferences": ["No 'in recent years' openers"],
        "rejected_patterns": [],
        "consistency_notes": [],
        "outstanding_todos": [],
        "completed_todos": ["Remove AI-flavored openers"],
        "manual_overrides": [],
    }

    def router(system, user):
        s = system.lower()
        # match by the most distinctive phrase in each prompt
        if "memory compactor" in s:
            return json.dumps(summ_payload)
        if "copy-editor" in s:
            return json.dumps(editor_payload)
        if "comprehensive revision plan" in s:
            return json.dumps(plan_payload)
        if "reading a manuscript for the first time" in s:
            return json.dumps(comp_payload)
        # default fall-through (should not happen in tests)
        return json.dumps(plan_payload)

    return router


def test_full_pipeline(tree, skill):
    llm = StubLLM(_route_factory(tree))

    # 1) comprehension
    card = ComprehensionAgent(llm).run(tree)
    assert card.title.startswith("Foo")
    assert "Libero" in card.datasets_or_benchmarks

    # 2) plan
    plan = PlannerAgent(llm).run(tree, skill, card, user_corrections="")
    assert isinstance(plan, Plan)
    assert plan.todos and plan.todos[0].category == "language"

    # 3) edit one todo
    sess = Session.new(skill.key, "in-memory.tex", "latex")
    sess.comprehension = card
    sess.comprehension_confirmed = True
    sess.plan = plan
    sess.plan_approved = True

    todo = plan.todos[0]
    result = EditorAgent(llm).run(todo, tree, skill, compact_memory="")

    # The two invalid suggestions must be dropped (id fabricated, before not in para).
    # The numeric-mutation suggestion is kept but flag_for_user must be True.
    assert len(result.suggestions) == 2
    valid = [s for s in result.suggestions if s.before == "In recent years, robotics"]
    assert len(valid) == 1
    assert valid[0].after == "Robotics"
    assert not valid[0].flag_for_user

    flagged = [s for s in result.suggestions if "issue X" in s.before]
    assert len(flagged) == 1
    assert flagged[0].flag_for_user is True, "guardrail must flip flag for numeric change"
    assert flagged[0].numeric_warnings, "guardrail must attach a report"

    sess.add_suggestions(result.suggestions)

    # 4) user actions
    sess.set_suggestion_status(valid[0].id, "accepted")
    sess.set_suggestion_status(flagged[0].id, "rejected")
    sess.set_todo_status(todo.id, "done", notes="opener removed")

    # 5) summarizer
    mem = SummarizerAgent(llm).compact(sess)
    assert "Remove AI-flavored openers" in mem.completed_todos
    assert "openers" in " ".join(mem.user_preferences)

    # 6) round-trip
    d = sess.to_dict()
    sess2 = Session.from_dict(d)
    assert sess2.id == sess.id
    assert len(sess2.suggestions) == 2
    assert sess2.plan.todos[0].status == "done"
