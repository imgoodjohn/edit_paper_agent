"""Agent layer.

Pipeline:
  ComprehensionAgent -> [user confirms] -> PlannerAgent -> [user approves]
    -> EditorAgent (per todo, per paragraph) -> [user accepts/rejects/modifies]
    -> SummarizerAgent (compact memory on demand)
"""
from .constraints import (
    HARD_CONSTRAINTS,
    integrity_clause,
    build_system_prompt,
)
from .schema import (
    ComprehensionCard,
    Plan,
    TodoItem,
    Suggestion,
    DecisionLogEntry,
    TODO_CATEGORIES,
    TODO_PRIORITY,
    SUGGESTION_SEVERITY,
)
from .comprehension_agent import ComprehensionAgent
from .planner_agent import PlannerAgent
from .editor_agent import EditorAgent, EditorRunResult
from .summarizer_agent import SummarizerAgent

__all__ = [
    "HARD_CONSTRAINTS",
    "integrity_clause",
    "build_system_prompt",
    "ComprehensionCard",
    "Plan",
    "TodoItem",
    "Suggestion",
    "DecisionLogEntry",
    "TODO_CATEGORIES",
    "TODO_PRIORITY",
    "SUGGESTION_SEVERITY",
    "ComprehensionAgent",
    "PlannerAgent",
    "EditorAgent",
    "EditorRunResult",
    "SummarizerAgent",
]
