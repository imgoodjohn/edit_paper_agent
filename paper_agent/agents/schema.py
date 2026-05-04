"""Structured I/O schemas shared by all agents.

We use plain dataclasses (not pydantic) to keep the dependency surface small.
Every dataclass has `from_dict` / `to_dict` for round-trip JSON.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Optional


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


# ---------------------------------------------------------------------------
# Phase 0 -- Comprehension
# ---------------------------------------------------------------------------

@dataclass
class ComprehensionCard:
    """AI's structured understanding of the paper, presented to the user
    for confirmation BEFORE any plan is generated."""

    title: str
    one_line_summary: str           # one sentence; what is this paper?
    field: str                       # broad area (e.g. "robot learning")
    subfield: str                    # narrow (e.g. "vision-language-action")
    problem: str                     # what gap does it address?
    contributions: list[str]         # 2–5 items
    methods: list[str]               # core technical approach
    key_claims: list[str]            # quantitative claims, faithful to text
    datasets_or_benchmarks: list[str]
    limitations_self_stated: list[str]
    confidence: float                # 0..1, how sure the AI is
    open_questions: list[str]        # things the AI is unsure about
    raw_response: str = ""           # original LLM output, for debugging

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d) -> "ComprehensionCard":
        # tolerate missing keys (older sessions)
        if isinstance(d, list):
            d = d[0] if d and isinstance(d[0], dict) else {}
        return cls(
            title=d.get("title", ""),
            one_line_summary=d.get("one_line_summary", ""),
            field=d.get("field", ""),
            subfield=d.get("subfield", ""),
            problem=d.get("problem", ""),
            contributions=list(d.get("contributions", [])),
            methods=list(d.get("methods", [])),
            key_claims=list(d.get("key_claims", [])),
            datasets_or_benchmarks=list(d.get("datasets_or_benchmarks", [])),
            limitations_self_stated=list(d.get("limitations_self_stated", [])),
            confidence=float(d.get("confidence", 0.5)),
            open_questions=list(d.get("open_questions", [])),
            raw_response=d.get("raw_response", ""),
        )


# ---------------------------------------------------------------------------
# Phase 1 -- Plan & Todo
# ---------------------------------------------------------------------------

# todo categories. Plan is NOT scope-limited; any of these may appear.
TODO_CATEGORIES = (
    "structure",      # missing/extra sections, ordering, length
    "content",        # logic flow, argumentation gaps, unsupported claims
    "compliance",     # journal rules: word limits, declarations, fmt
    "language",       # grammar, clarity, AI-flavor removal
    "consistency",    # terminology / notation drift across sections
    "figures_tables", # caption clarity, reference consistency
    "references",     # cite style, missing year, broken \ref
)

TODO_PRIORITY = ("critical", "high", "medium", "low")


_HUMAN_KEYWORDS = (
    # English
    "run new experiment", "new experiment", "collect data", "collect more",
    "re-run", "rerun", "ablation study", "add results", "add experiment",
    "missing results", "data anomaly", "data inconsistenc", "numerical error",
    "verify number", "reconcile", "implement code", "implement algorithm",
    # Chinese
    "实验", "补充实验", "补做实验", "数据异常", "数据不一致",
    "重新实验", "重跑", "收集数据", "采集数据",
    "数值错误", "核实数字", "对齐数字", "实现代码", "实现算法",
    "验证结果", "消融实验", "对比实验",
)


@dataclass
class TodoItem:
    """One actionable revision task. EditorAgent processes one at a time."""

    id: str
    category: str                    # see TODO_CATEGORIES
    priority: str                    # see TODO_PRIORITY
    title: str                       # short imperative, "Tighten abstract to 150w"
    description: str                 # full rationale, what to do, why
    target_section_ids: list[str] = field(default_factory=list)
    target_paragraph_ids: list[str] = field(default_factory=list)
    expected_outcome: str = ""       # what success looks like
    status: str = "pending"          # pending|in_progress|done|skipped|failed
    notes: str = ""                  # filled by editor when done
    needs_human: bool = False        # editor must not auto-edit; flag for manual review

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "TodoItem":
        raw_desc = d.get("description", "")
        if isinstance(raw_desc, list):
            description = "\n".join(str(x) for x in raw_desc)
        else:
            description = str(raw_desc) if raw_desc else ""
        # needs_human: prefer AI-provided value, fall back to keyword scan
        explicit = d.get("needs_human")
        if explicit is not None:
            needs_human = bool(explicit)
        else:
            combined = d.get("title", "") + " " + description
            low = combined.lower()  # for English matching
            needs_human = any(kw in low if kw.isascii() else kw in combined
                              for kw in _HUMAN_KEYWORDS)
        return cls(
            id=d.get("id") or _uid("todo"),
            category=d.get("category", "language"),
            priority=d.get("priority", "medium"),
            title=d.get("title", ""),
            description=description,
            target_section_ids=list(d.get("target_section_ids", [])),
            target_paragraph_ids=list(d.get("target_paragraph_ids", [])),
            expected_outcome=d.get("expected_outcome", ""),
            status=d.get("status", "pending"),
            notes=d.get("notes", ""),
            needs_human=needs_human,
        )


@dataclass
class Plan:
    """Whole-paper revision plan. Generated once by PlannerAgent.

    `overall_strategy` is a free-form paragraph the user will read first.
    """

    overall_strategy: str
    risks: list[str]                 # things the AI flagged but won't auto-fix
    todos: list[TodoItem]
    journal_target: Optional[str] = None
    raw_response: str = ""

    def to_dict(self) -> dict:
        return {
            "overall_strategy": self.overall_strategy,
            "risks": list(self.risks),
            "todos": [t.to_dict() for t in self.todos],
            "journal_target": self.journal_target,
            "raw_response": self.raw_response,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Plan":
        return cls(
            overall_strategy=d.get("overall_strategy", ""),
            risks=list(d.get("risks", [])),
            todos=[TodoItem.from_dict(t) for t in d.get("todos", [])],
            journal_target=d.get("journal_target"),
            raw_response=d.get("raw_response", ""),
        )


# ---------------------------------------------------------------------------
# Phase 2 -- Edit suggestions
# ---------------------------------------------------------------------------

SUGGESTION_SEVERITY = ("info", "warning", "critical")


@dataclass
class Suggestion:
    """A single proposed edit. Maps onto one paragraph (or part of one).

    The Web UI renders this as a GitHub-PR-style review comment with
    accept / reject / modify buttons.
    """

    id: str
    todo_id: str
    paragraph_id: str
    section_id: str
    category: str                    # one of TODO_CATEGORIES
    severity: str                    # see SUGGESTION_SEVERITY
    before: str                      # exact substring of paragraph.text
    after: str                       # proposed replacement
    rationale: str                   # 1–3 sentences, in the user's locale
    flag_for_user: bool = False      # true if numeric/citation touched
    numeric_warnings: list[dict] = field(default_factory=list)  # NumberGuard report
    status: str = "pending"          # pending|accepted|rejected|modified
    user_modified_after: Optional[str] = None  # if user chose "modify"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Suggestion":
        return cls(
            id=d.get("id") or _uid("sug"),
            todo_id=d.get("todo_id", ""),
            paragraph_id=d.get("paragraph_id", ""),
            section_id=d.get("section_id", ""),
            category=d.get("category", "language"),
            severity=d.get("severity", "info"),
            before=d.get("before", ""),
            after=d.get("after", ""),
            rationale=d.get("rationale", ""),
            flag_for_user=bool(d.get("flag_for_user", False)),
            numeric_warnings=list(d.get("numeric_warnings", [])),
            status=d.get("status", "pending"),
            user_modified_after=d.get("user_modified_after"),
        )


# ---------------------------------------------------------------------------
# Decision log entries (memory)
# ---------------------------------------------------------------------------

@dataclass
class DecisionLogEntry:
    ts: float                        # unix epoch seconds
    kind: str                        # "comprehension_confirmed", "plan_approved",
                                     # "todo_started", "todo_done",
                                     # "suggestion_accepted", "suggestion_rejected",
                                     # "suggestion_modified", "compact"
    payload: dict = field(default_factory=dict)

    @staticmethod
    def now(kind: str, **payload: Any) -> "DecisionLogEntry":
        return DecisionLogEntry(ts=time.time(), kind=kind, payload=dict(payload))

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Tool-calling log (persisted per session so UI survives reload)
# ---------------------------------------------------------------------------

@dataclass
class ToolCallRecord:
    """One tool invocation by the ToolAgent."""

    id: str
    todo_id: str
    tool: str
    args: dict
    result_summary: str
    result: dict = field(default_factory=dict)   # full result (capped) for UI
    ts: float = field(default_factory=time.time)
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ToolCallRecord":
        return cls(
            id=d.get("id", _uid("tc")),
            todo_id=d.get("todo_id", ""),
            tool=d.get("tool", ""),
            args=d.get("args", {}),
            result_summary=d.get("result_summary", ""),
            result=d.get("result", {}),
            ts=float(d.get("ts", time.time())),
            error=d.get("error"),
        )
