"""Tests for the numeric / citation guardrail."""
from __future__ import annotations

from paper_agent.guardrails import NumberGuard, extract_numbers


def test_no_change_clean():
    g = NumberGuard()
    s = "Our method achieves 92.4% accuracy on dataset A."
    r = g.check("p1", s, s)
    assert not r.has_changes


def test_pure_grammar_fix_passes():
    g = NumberGuard()
    before = "The model is achieve 92.4% accuracy and 88.1% F1."
    after = "The model achieves 92.4% accuracy and 88.1% F1."
    r = g.check("p1", before, after)
    assert not r.has_changes


def test_numeric_change_flagged_critical():
    g = NumberGuard()
    before = "Accuracy improved to 92.4%."
    after = "Accuracy improved to 95.1%."
    r = g.check("p1", before, after)
    crits = r.critical()
    assert len(crits) == 1
    assert crits[0].kind == "numeric"
    assert "95.1" in crits[0].added[0] or "95.1%" in crits[0].added[0]
    assert "92.4" in crits[0].removed[0] or "92.4%" in crits[0].removed[0]


def test_citation_renumber_flagged_critical():
    g = NumberGuard()
    before = "As shown in [12], this works."
    after = "As shown in [13], this works."
    r = g.check("p1", before, after)
    crits = r.critical()
    assert any(c.kind == "numbered_citation" for c in crits)


def test_latex_cite_key_change_flagged():
    g = NumberGuard()
    before = r"This is shown by \cite{smith2023}."
    after = r"This is shown by \cite{smith2024}."
    r = g.check("p1", before, after)
    crits = r.critical()
    assert any(c.kind == "latex_cite_key" for c in crits)


def test_label_change_warning_not_critical():
    g = NumberGuard()
    before = r"See Eq.~\ref{eq:foo}."
    after = r"See Eq.~\ref{eq:bar}."
    r = g.check("p1", before, after)
    # ref keys are warning-level (intentional rename allowed if user accepts)
    assert r.has_changes
    assert all(c.severity == "warning" for c in r.changes)


def test_extract_numbers_classes():
    out = extract_numbers(r"We achieved 92.4% on \cite{x2023} and [5].")
    assert any("92.4" in n for n in out["numeric"])
    assert "x2023" in out["latex_cite_key"]
    assert "[5]" in out["numbered_citation"]


def test_multiplicity_dedup_flagged():
    g = NumberGuard()
    # Original lists value twice (e.g. 92.4 in two columns); rewrite drops one.
    before = "The score 92.4 appears twice: 92.4 and 92.4."
    after = "The score 92.4 appears twice: 92.4."
    r = g.check("p1", before, after)
    assert r.critical(), "dropping a duplicated number must be flagged"
