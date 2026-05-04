"""ToolAgent: ReAct-style editor that calls tools to inspect the document.

Loop (up to MAX_STEPS):
  1. Send system prompt + message history to LLM.
  2. Parse {"thought": "...", "tool": "<name>", "args": {...}}.
  3. Execute tool, append result as next user message.
  4. When tool == "finish", validate suggestions and return.

Context management:
  - Hard cap of MAX_HISTORY_CHARS; when exceeded the oldest middle messages
    are compressed to a one-line "[X tool calls summarised]" stub so the
    first (todo context) and last (recent results) messages are always kept.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, Optional

from ..ir import DocumentTree
from ..llm import LLMClient, ModelTier
from ..llm.client import _extract_json
from ..skills import JournalSkill
from . import tools as _tools
from .schema import Suggestion, ToolCallRecord, TodoItem, _uid
from .constraints import build_system_prompt

MAX_STEPS = 15
MAX_HISTORY_CHARS = 14_000

TOOL_SPEC = """\
## Available tools

Return exactly ONE JSON object per turn:
{"thought": "<your reasoning>", "tool": "<name>", "args": {<args>}}

### get_toc
Args: {}
Get full table of contents with section ids and levels. Start here.

### get_abstract
Args: {}
Get the abstract paragraph text and its paragraph_id.

### get_references
Args: {}
Get the reference list (up to 50 entries).

### get_section_list
Args: {}
List all section ids and titles so you know where to look.

### read_section
Args: {"section_id": "sec-xxx"}
Return paragraphs (with ids) for a section.

### read_paragraph
Args: {"paragraph_id": "para-xxx"}
Full text of one paragraph.

### search_text
Args: {"query": "...", "case_sensitive": false, "is_regex": false, "section_id": "sec-xxx (optional)"}
Find occurrences across the document (or within one section).

### get_lines
Args: {"start_line": 1, "end_line": 30}
Raw source lines by 1-based line number (useful for LaTeX formatting issues).

### fetch_url
Args: {"url": "https://..."}
Fetch a web page — journal author guidelines, citation style, etc.

### count_stats
Args: {"scope": "full|abstract|references|section|paragraph", "section_id": "sec-xxx (if scope=section)", "paragraph_id": "para-xxx (if scope=paragraph)"}
Count words in the whole document, abstract, references, a specific section, or a single paragraph. Also returns per-section breakdown for scope=full.

### finish
Args: {"suggestions": [...], "notes": "..."}
End the loop. `suggestions` uses the standard schema:
[{
  "paragraph_id": "para-xxx",
  "before": "<exact substring>",
  "after": "<replacement>",
  "rationale": "...",
  "category": "language|structure|compliance|content|consistency|figures_tables|references",
  "severity": "info|warning|critical",
  "flag_for_user": false
}]
"""


@dataclass
class ToolAgentResult:
    todo_id: str
    suggestions: list[Suggestion]
    tool_calls: list[ToolCallRecord]
    notes: str = ""


class ToolAgent:
    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    # ---------------------------------------------------------------- public

    def run(
        self,
        todo: TodoItem,
        tree: DocumentTree,
        skill: JournalSkill,
        compact_memory: str = "",
        tier: ModelTier = ModelTier.SMART,
        language: str = "en",
        model: Optional[str] = None,
        on_tool_call: Optional[Callable[[ToolCallRecord], None]] = None,
    ) -> ToolAgentResult:
        system = self._system(skill, compact_memory, language)
        messages: list[dict] = [
            {"role": "user", "content": self._initial_user(todo, tree)},
        ]

        tool_calls: list[ToolCallRecord] = []
        suggestions: list[Suggestion] = []
        notes = ""

        for _ in range(MAX_STEPS):
            messages = _compress(messages)
            raw = self.llm.complete_messages(
                messages=[{"role": "system", "content": system}] + messages,
                tier=tier,
                temperature=0.1,
                max_tokens=4096,
                model=model,
            )
            messages.append({"role": "assistant", "content": raw})

            try:
                parsed = _extract_json(raw)
            except Exception:
                parsed = {}

            tool_name = parsed.get("tool", "")
            args = parsed.get("args", {})
            if not isinstance(args, dict):
                args = {}

            if tool_name == "finish":
                raw_sugs = args.get("suggestions", [])
                notes = str(args.get("notes", ""))
                suggestions = self._validate_suggestions(raw_sugs, todo, tree)
                break

            if not tool_name:
                # Model may have returned suggestions directly (no tool wrapper)
                raw_sugs = parsed.get("suggestions", [])
                if raw_sugs:
                    suggestions = self._validate_suggestions(raw_sugs, todo, tree)
                    notes = str(parsed.get("notes", ""))
                break

            tc, result = self._execute(tool_name, args, todo.id, tree)
            tool_calls.append(tc)
            if on_tool_call:
                try:
                    on_tool_call(tc)
                except Exception:
                    pass

            result_text = json.dumps(result, ensure_ascii=False)
            messages.append({
                "role": "user",
                "content": f"[TOOL RESULT: {tool_name}]\n{result_text[:2500]}",
            })

        return ToolAgentResult(
            todo_id=todo.id,
            suggestions=suggestions,
            tool_calls=tool_calls,
            notes=notes,
        )

    # --------------------------------------------------------------- helpers

    def _system(self, skill: JournalSkill, memory: str, language: str) -> str:
        rules = "\n".join(f"- {r}" for r in skill.compliance_rules[:12])
        parts = [
            "You are a precise academic copy-editor. Use the provided tools to "
            "inspect the paper, then call `finish` with your suggestions.",
            TOOL_SPEC,
            "## Journal compliance rules",
            rules or "(none specified)",
            "## Hard constraints (non-negotiable)",
            "- Never change numbers, statistics, p-values, citations, or \\ref keys.",
            "- `before` must be an EXACT substring of the paragraph text.",
            "- Prefer the smallest change that achieves the goal.",
            "- Remove AI-flavor phrases (\"in recent years\", \"it is worth noting\", etc.).",
            f"- Write `rationale` in: {language}",
        ]
        if memory.strip():
            parts += ["## Session memory (stay consistent with prior decisions)", memory.strip()]
        return "\n\n".join(parts)

    def _initial_user(self, todo: TodoItem, tree: DocumentTree) -> str:
        toc = tree.toc()
        toc_str = "\n".join(f"  {s['id']}: {s['title']}" for s in toc[:25])
        return (
            f"# TODO to execute\n"
            f"id: {todo.id}\n"
            f"category: {todo.category}\n"
            f"priority: {todo.priority}\n"
            f"title: {todo.title}\n"
            f"description: {todo.description}\n"
            f"expected_outcome: {todo.expected_outcome}\n\n"
            f"# Document overview (use tools to read content)\n"
            f"Title: {tree.title}\n"
            f"Sections:\n{toc_str}\n\n"
            "Start by reading the relevant section(s), then make your suggestions "
            "via `finish`. Use `search_text` or `get_lines` for targeted inspection."
        )

    def _execute(
        self, name: str, args: dict, todo_id: str, tree: DocumentTree
    ) -> tuple[ToolCallRecord, dict]:
        dispatch = {
            "get_toc":           lambda: _tools.get_toc(tree),
            "get_abstract":      lambda: _tools.get_abstract(tree),
            "get_references":    lambda: _tools.get_references(tree),
            "get_section_list": lambda: _tools.get_section_list(tree),
            "read_section":     lambda: _tools.read_section(tree, args.get("section_id", "")),
            "read_paragraph":   lambda: _tools.read_paragraph(tree, args.get("paragraph_id", "")),
            "search_text":      lambda: _tools.search_text(
                tree,
                query=str(args.get("query", "")),
                case_sensitive=bool(args.get("case_sensitive", False)),
                is_regex=bool(args.get("is_regex", False)),
                section_id=args.get("section_id"),
            ),
            "get_lines": lambda: _tools.get_lines(
                tree,
                start_line=int(args.get("start_line", 1)),
                end_line=int(args.get("end_line", 10)),
            ),
            "count_stats": lambda: _tools.count_stats(
                tree,
                scope=args.get("scope", "full"),
                section_id=args.get("section_id"),
                paragraph_id=args.get("paragraph_id"),
            ),
            "fetch_url":   lambda: _tools.fetch_url(str(args.get("url", ""))),
        }

        error: Optional[str] = None
        if name in dispatch:
            try:
                result = dispatch[name]()
            except Exception as e:
                result = {"error": str(e)}
                error = str(e)
        else:
            result = {"error": f"unknown tool '{name}'"}
            error = result["error"]

        summary = _summarise(name, result)
        # Cap stored result to avoid bloating session JSON
        stored_result = {k: v for k, v in result.items() if k != "text"}  # drop long text field
        if "text" in result:
            stored_result["text"] = result["text"][:400]
        tc = ToolCallRecord(
            id=_uid("tc"),
            todo_id=todo_id,
            tool=name,
            args=args,
            result_summary=summary,
            result=stored_result,
            error=error,
        )
        return tc, result

    def _validate_suggestions(
        self, raw: list, todo: TodoItem, tree: DocumentTree
    ) -> list[Suggestion]:
        out: list[Suggestion] = []
        for s in raw:
            if not isinstance(s, dict):
                continue
            pid = s.get("paragraph_id", "")
            para = tree.find_paragraph(pid)
            if para is None:
                continue
            before = s.get("before", "")
            after = s.get("after", "")
            if not before or before not in para.text:
                continue
            out.append(Suggestion(
                id=_uid("sug"),
                todo_id=todo.id,
                paragraph_id=pid,
                section_id=para.metadata.get("section_id", ""),
                category=s.get("category", todo.category),
                severity=s.get("severity", "info"),
                before=before,
                after=after,
                rationale=s.get("rationale", ""),
                flag_for_user=bool(s.get("flag_for_user", False)),
            ))
        return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compress(messages: list[dict]) -> list[dict]:
    """Drop middle messages when the conversation grows too long."""
    total = sum(len(m["content"]) for m in messages)
    if total <= MAX_HISTORY_CHARS or len(messages) <= 4:
        return messages
    first = messages[0]
    last = messages[-3:]
    stub = {"role": "user", "content": f"[{len(messages) - 4} earlier messages compressed to save context]"}
    return [first, stub] + last


def _summarise(tool: str, result: dict) -> str:
    if result.get("error"):
        return f"error: {result['error']}"
    if tool == "get_toc":
        return f"{len(result.get('toc', []))} sections — {result.get('title', '')}"
    if tool == "get_abstract":
        return result.get("text", "")[:100]
    if tool == "get_references":
        return f"{result.get('count', 0)} references"
    if tool == "get_section_list":
        return f"{len(result.get('sections', []))} sections"
    if tool == "read_section":
        return f"{result.get('n_paragraphs', 0)} paragraphs — {result.get('title', '')}"
    if tool == "read_paragraph":
        return result.get("text", "")[:100]
    if tool == "search_text":
        return f"{result.get('total_matches', 0)} match(es) for \"{result.get('query', '')}\""
    if tool == "get_lines":
        return f"lines {result.get('start_line')}–{result.get('end_line')} of {result.get('total_lines')}"
    if tool == "fetch_url":
        return f"HTTP {result.get('status', '?')} · {len(result.get('text', ''))} chars"
    return str(result)[:120]
