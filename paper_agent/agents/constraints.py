"""Hard constraints injected into every agent's system prompt.

Per user spec:
  * All journals only allow grammar / logic / style / compliance fixes.
  * Agents must NEVER fabricate or alter experimental data, numeric
    values, statistical results, citation indices, or reference keys.
  * Agents should avoid AI-flavored writing (overly hedged, repetitive
    transition words, generic praise, etc.).
  * Any number/citation change must be surfaced explicitly so the
    downstream guardrail and the user can see it. We require the agent
    to wrap edits in \\replaced[remark={...}]{new}{old} (LaTeX) or
    return structured JSON suggestions (DOCX path), and to emit a
    `numeric_change` flag in the suggestion payload when a digit is
    touched intentionally (e.g. fixing an obvious typo).
"""
from __future__ import annotations

HARD_CONSTRAINTS = """\
INTEGRITY RULES — read carefully, these are non-negotiable:

1. DO NOT modify any experimental number, statistic, p-value, accuracy,
   percentage, dataset size, or unit. This includes results in tables,
   figures, captions, and inline text.
2. DO NOT add, remove, renumber, or reorder citations. Preserve every
   \\cite{...}, [12], (Smith et al., 2023) exactly as written.
3. DO NOT modify \\ref / \\eqref / \\label keys, equation numbers, or
   figure/table identifiers.
4. DO NOT invent new findings, claims, methods, or references. You may
   only rewrite existing prose for clarity, grammar, or style.
5. If you genuinely believe a number or citation is mistaken (e.g. a
   typo where the same value appears differently elsewhere), DO NOT
   silently change it. Instead, attach a `flag_for_user` note in the
   suggestion describing the suspected issue. The user decides.
6. Avoid AI-flavored prose. Specifically:
     - no hollow openers ("In recent years", "It is worth noting that")
     - no repetitive hedges ("notably", "interestingly", "moreover")
       inserted where the original had none
     - no over-explanation of trivial steps
     - preserve the author's voice; do not regress informal-but-clear
       writing into corporate boilerplate
7. Output every textual change as a structured suggestion (see schema in
   the user message). Never output a fully-rewritten paragraph as the
   primary action — diffs only.
"""


def integrity_clause(extra: str = "") -> str:
    if extra:
        return HARD_CONSTRAINTS + "\nADDITIONAL RULES:\n" + extra.strip() + "\n"
    return HARD_CONSTRAINTS


def build_system_prompt(role_description: str, extra_rules: str = "") -> str:
    """Compose a system prompt with role + integrity rules."""
    return (
        role_description.strip()
        + "\n\n"
        + integrity_clause(extra_rules)
    )
