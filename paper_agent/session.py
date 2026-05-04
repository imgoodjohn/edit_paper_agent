"""Session state -- the source of truth for one revision run.

A Session bundles:
  * the parsed DocumentTree
  * the journal skill key
  * the comprehension card (after user confirms)
  * the plan (after user approves)
  * the decision log (every accept / reject / modify)
  * the running compact summary (filled by SummarizerAgent)
  * an index of suggestions keyed by id

Persistence: JSON file on disk under <repo>/sessions/<session_id>.json.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from .agents.schema import (
    ComprehensionCard,
    DecisionLogEntry,
    Plan,
    Suggestion,
    TodoItem,
    ToolCallRecord,
)


SESSION_DIR = Path(__file__).resolve().parents[1] / "sessions"


@dataclass
class CompactMemory:
    """Output of SummarizerAgent.compact()."""

    compact_summary: str = ""
    user_preferences: list[str] = field(default_factory=list)
    rejected_patterns: list[dict] = field(default_factory=list)
    consistency_notes: list[dict] = field(default_factory=list)
    outstanding_todos: list[str] = field(default_factory=list)
    completed_todos: list[str] = field(default_factory=list)
    manual_overrides: list[str] = field(default_factory=list)
    last_compacted_log_index: int = 0

    def to_dict(self) -> dict:
        return {
            "compact_summary": self.compact_summary,
            "user_preferences": self.user_preferences,
            "rejected_patterns": self.rejected_patterns,
            "consistency_notes": self.consistency_notes,
            "outstanding_todos": self.outstanding_todos,
            "completed_todos": self.completed_todos,
            "manual_overrides": self.manual_overrides,
            "last_compacted_log_index": self.last_compacted_log_index,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CompactMemory":
        return cls(
            compact_summary=d.get("compact_summary", ""),
            user_preferences=list(d.get("user_preferences", [])),
            rejected_patterns=list(d.get("rejected_patterns", [])),
            consistency_notes=list(d.get("consistency_notes", [])),
            outstanding_todos=list(d.get("outstanding_todos", [])),
            completed_todos=list(d.get("completed_todos", [])),
            manual_overrides=list(d.get("manual_overrides", [])),
            last_compacted_log_index=int(d.get("last_compacted_log_index", 0)),
        )


@dataclass
class Session:
    id: str
    journal_key: str
    source_path: str                     # original uploaded file
    source_type: str                     # "latex" | "docx"
    created_at: float = field(default_factory=time.time)
    comprehension: Optional[ComprehensionCard] = None
    comprehension_confirmed: bool = False
    user_corrections: str = ""           # free-form text the user added
    plan: Optional[Plan] = None
    plan_approved: bool = False
    suggestions: dict[str, Suggestion] = field(default_factory=dict)
    decision_log: list[DecisionLogEntry] = field(default_factory=list)
    memory: CompactMemory = field(default_factory=CompactMemory)
    tool_log: list[ToolCallRecord] = field(default_factory=list)
    review_report: Optional[dict] = None    # last ReviewReport.to_dict()
    ai_detection: Optional[dict] = None    # last AIDetectionResult.to_dict()

    # ---------------------------------------------------------------- factory

    @staticmethod
    def new(journal_key: str, source_path: str, source_type: str) -> "Session":
        return Session(
            id=f"sess-{uuid.uuid4().hex[:12]}",
            journal_key=journal_key,
            source_path=str(source_path),
            source_type=source_type,
        )

    # --------------------------------------------------------- decision log

    def log(self, kind: str, **payload) -> DecisionLogEntry:
        e = DecisionLogEntry.now(kind, **payload)
        self.decision_log.append(e)
        return e

    def recent_log(self, n: int = 30) -> list[DecisionLogEntry]:
        return self.decision_log[-n:]

    # --------------------------------------------------------- suggestions

    def add_suggestions(self, items: Iterable[Suggestion]) -> None:
        for s in items:
            self.suggestions[s.id] = s

    def set_suggestion_status(
        self, sid: str, status: str, modified_after: Optional[str] = None
    ) -> Suggestion:
        sug = self.suggestions[sid]
        sug.status = status
        if modified_after is not None:
            sug.user_modified_after = modified_after
        kind = {
            "accepted": "suggestion_accepted",
            "rejected": "suggestion_rejected",
            "modified": "suggestion_modified",
        }.get(status, "suggestion_status")
        self.log(
            kind,
            suggestion_id=sid,
            paragraph_id=sug.paragraph_id,
            todo_id=sug.todo_id,
            before=sug.before,
            after=sug.user_modified_after or sug.after,
            rationale=sug.rationale,
        )
        return sug

    # ------------------------------------------------------------- todos

    def todos(self) -> list[TodoItem]:
        return self.plan.todos if self.plan else []

    def todo(self, todo_id: str) -> Optional[TodoItem]:
        for t in self.todos():
            if t.id == todo_id:
                return t
        return None

    def set_todo_status(self, todo_id: str, status: str, notes: str = "") -> None:
        t = self.todo(todo_id)
        if t is None:
            return
        t.status = status
        if notes:
            t.notes = notes
        self.log(
            "todo_done" if status == "done" else "todo_status",
            todo_id=todo_id,
            status=status,
            notes=notes,
        )

    # ------------------------------------------------------- persistence

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "journal_key": self.journal_key,
            "source_path": self.source_path,
            "source_type": self.source_type,
            "created_at": self.created_at,
            "comprehension": self.comprehension.to_dict() if self.comprehension else None,
            "comprehension_confirmed": self.comprehension_confirmed,
            "user_corrections": self.user_corrections,
            "plan": self.plan.to_dict() if self.plan else None,
            "plan_approved": self.plan_approved,
            "suggestions": {sid: s.to_dict() for sid, s in self.suggestions.items()},
            "decision_log": [e.to_dict() for e in self.decision_log],
            "memory": self.memory.to_dict(),
            "tool_log": [t.to_dict() for t in self.tool_log],
            "review_report": self.review_report,
            "ai_detection": self.ai_detection,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Session":
        s = cls(
            id=d["id"],
            journal_key=d["journal_key"],
            source_path=d["source_path"],
            source_type=d["source_type"],
            created_at=d.get("created_at", time.time()),
            comprehension=ComprehensionCard.from_dict(d["comprehension"])
            if d.get("comprehension")
            else None,
            comprehension_confirmed=d.get("comprehension_confirmed", False),
            user_corrections=d.get("user_corrections", ""),
            plan=Plan.from_dict(d["plan"]) if d.get("plan") else None,
            plan_approved=d.get("plan_approved", False),
            suggestions={
                sid: Suggestion.from_dict(v)
                for sid, v in d.get("suggestions", {}).items()
            },
            decision_log=[
                DecisionLogEntry(ts=e["ts"], kind=e["kind"], payload=e.get("payload", {}))
                for e in d.get("decision_log", [])
            ],
            memory=CompactMemory.from_dict(d.get("memory", {})),
            tool_log=[ToolCallRecord.from_dict(t) for t in d.get("tool_log", [])],
            review_report=d.get("review_report"),
            ai_detection=d.get("ai_detection"),
        )
        return s

    def save(self, dir: Optional[Path] = None) -> Path:
        d = Path(dir) if dir else SESSION_DIR
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{self.id}.json"
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    @classmethod
    def load(cls, session_id: str, dir: Optional[Path] = None) -> "Session":
        d = Path(dir) if dir else SESSION_DIR
        path = d / f"{session_id}.json"
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))
