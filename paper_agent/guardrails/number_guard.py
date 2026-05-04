"""Numeric / data integrity guardrail.

Goal
----
The agents are explicitly forbidden from changing experimental numbers,
data, citation keys or reference indices.  This module provides the
*detection* layer: given the original and proposed paragraph text,
it extracts the multiset of numeric / citation tokens and reports any
mismatch.

Behavior (per user spec): we **flag** changes for user confirmation
(does not silently block). The downstream Web UI shows a high-severity
warning; the user can still accept if they intentionally fixed a typo.

Token classes
-------------
* numeric        - integers, decimals, percentages, scientific notation,
                   ranges, units (e.g. "92.4%", "1.2e-3", "5 ms", "10x")
* citation       - "[12]", "[3, 5-7]", "(Smith et al., 2023)"
* latex_cite_key - \\cite{foo}, \\citep{bar2023} keys
* latex_ref_key  - \\ref{eq:1}, \\eqref{...}, \\label{...}

If any of those multisets differ between before and after, we emit a
NumberChange.  Adding a unit word (e.g. "5" -> "5 ms") is treated as a
change (added "ms" token).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

# ---------------------------------------------------------------------------
# Token extractors
# ---------------------------------------------------------------------------

# Match e.g. "92.4", "1,234", "1.2e-3", "1.5\\times10^{3}", "10%"
NUMERIC_RE = re.compile(
    r"""
    (?<![A-Za-z_])                  # not part of an identifier
    (?:
        \d+(?:[.,]\d+)*             # 1 234,567.89
        (?:\s*[eE][+-]?\d+)?        # scientific
        \s*%?                       # optional percent
    )
    """,
    re.VERBOSE,
)

# Numbered citations like [12], [3,5-7]
NUM_CITE_RE = re.compile(r"\[\s*\d+(?:\s*[,-]\s*\d+)*\s*\]")

# Author-year citation: (Smith et al., 2023) / (Smith, 2023; Jones, 2024)
AY_CITE_RE = re.compile(
    r"\(([A-Z][A-Za-z\-]+(?:\s+et\s+al\.?)?(?:\s*,\s*\d{4}[a-z]?)?(?:\s*;\s*[A-Z][A-Za-z\-]+(?:\s+et\s+al\.?)?\s*,\s*\d{4}[a-z]?)*)\)"
)

LATEX_CITE_RE = re.compile(
    r"\\(?:cite|citep|citet|citeauthor|citeyear|footcite)\*?\s*(?:\[[^\]]*\])*\s*\{([^}]+)\}"
)
LATEX_REF_RE = re.compile(
    r"\\(?:ref|eqref|autoref|cref|Cref|pageref|nameref)\*?\s*\{([^}]+)\}"
)
LATEX_LABEL_RE = re.compile(r"\\label\s*\{([^}]+)\}")


def _normalize_num(tok: str) -> str:
    return re.sub(r"\s+", "", tok)


def extract_numbers(text: str) -> dict[str, list[str]]:
    """Return token multisets keyed by class.

    Lists are returned (not sets) so multiplicity is preserved -- e.g. an
    accidental dedup of "92.4 / 92.4 / 88.1" -> "92.4 / 88.1" is caught.
    """
    numerics = [_normalize_num(m.group(0)) for m in NUMERIC_RE.finditer(text)]
    num_cites = [m.group(0).replace(" ", "") for m in NUM_CITE_RE.finditer(text)]
    ay_cites = [m.group(1) for m in AY_CITE_RE.finditer(text)]
    cite_keys = []
    for m in LATEX_CITE_RE.finditer(text):
        cite_keys.extend(k.strip() for k in m.group(1).split(","))
    ref_keys = [m.group(1).strip() for m in LATEX_REF_RE.finditer(text)]
    label_keys = [m.group(1).strip() for m in LATEX_LABEL_RE.finditer(text)]
    return {
        "numeric": sorted(numerics),
        "numbered_citation": sorted(num_cites),
        "author_year_citation": sorted(ay_cites),
        "latex_cite_key": sorted(cite_keys),
        "latex_ref_key": sorted(ref_keys),
        "latex_label_key": sorted(label_keys),
    }


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------

@dataclass
class NumberChange:
    """A single class-level token-set diff."""

    kind: str          # one of the keys returned by extract_numbers()
    added: list[str]
    removed: list[str]
    severity: str      # "critical" | "warning"

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "added": self.added,
            "removed": self.removed,
            "severity": self.severity,
        }


@dataclass
class NumberGuardReport:
    paragraph_id: str
    changes: list[NumberChange] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.changes)

    def critical(self) -> list[NumberChange]:
        return [c for c in self.changes if c.severity == "critical"]

    def to_dict(self) -> dict:
        return {
            "paragraph_id": self.paragraph_id,
            "changes": [c.to_dict() for c in self.changes],
            "has_changes": self.has_changes,
        }


# Tokens whose mutation is *always* critical (changing data integrity).
_CRITICAL_KINDS = {"numeric", "numbered_citation", "latex_cite_key"}


class NumberGuard:
    """Compare before/after text and report disallowed token mutations."""

    def check(
        self,
        paragraph_id: str,
        before: str,
        after: str,
    ) -> NumberGuardReport:
        b = extract_numbers(before)
        a = extract_numbers(after)
        report = NumberGuardReport(paragraph_id=paragraph_id)
        for kind in b.keys():
            added, removed = _multiset_diff(a[kind], b[kind])
            if not added and not removed:
                continue
            severity = "critical" if kind in _CRITICAL_KINDS else "warning"
            report.changes.append(
                NumberChange(
                    kind=kind, added=added, removed=removed, severity=severity
                )
            )
        return report

    def check_many(
        self, items: Iterable[tuple[str, str, str]]
    ) -> list[NumberGuardReport]:
        return [self.check(pid, b, a) for pid, b, a in items]


def _multiset_diff(a: list[str], b: list[str]) -> tuple[list[str], list[str]]:
    """Return (added, removed) where multiplicity matters."""
    from collections import Counter

    ca, cb = Counter(a), Counter(b)
    added = list((ca - cb).elements())
    removed = list((cb - ca).elements())
    return sorted(added), sorted(removed)
