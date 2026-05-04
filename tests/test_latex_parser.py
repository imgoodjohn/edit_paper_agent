"""Tests for LaTeXParser.

Run from repo root:  pytest tests/test_latex_parser.py -v
"""
from __future__ import annotations

import textwrap

from paper_agent.parsers import LaTeXParser

SAMPLE = textwrap.dedent(r"""
    \documentclass{article}
    \title{A Sample Paper on Foo}
    \begin{document}
    \maketitle

    \begin{abstract}
    We propose a new method that improves accuracy by 4.2\% over prior
    work~\cite{smith2023}. Our approach is simple. It works well.
    \end{abstract}

    \section{Introduction}
    Recent advances~\cite{smith2023, jones2024} have shown great promise.
    However, existing methods suffer from issue X. We address this gap.

    This is a second paragraph in the introduction. It has two sentences.

    \subsection{Motivation}
    Our motivation is threefold.

    \section{Method}
    \begin{equation}
    y = mx + b \label{eq:linear}
    \end{equation}
    The linear model in Eq.~\ref{eq:linear} is a baseline. We extend it.

    \section{Conclusion}
    We presented a new method.

    \end{document}
""").strip()


def test_parses_title_and_abstract():
    tree = LaTeXParser().parse(SAMPLE)
    assert "Sample Paper" in tree.title
    assert tree.abstract is not None
    assert "4.2%" in tree.abstract.text or "4.2" in tree.abstract.text
    assert len(tree.abstract.sentences) >= 2


def test_section_hierarchy():
    tree = LaTeXParser().parse(SAMPLE)
    titles = [s.title for s in tree.sections]
    assert titles == ["Introduction", "Method", "Conclusion"]
    intro = tree.sections[0]
    assert any(c.title == "Motivation" and c.level == 2 for c in intro.children)


def test_paragraph_split():
    tree = LaTeXParser().parse(SAMPLE)
    intro = tree.sections[0]
    # Two body paragraphs (not counting subsection)
    assert len(intro.paragraphs) == 2
    assert intro.paragraphs[0].text != intro.paragraphs[1].text


def test_equation_skipped_from_text():
    tree = LaTeXParser().parse(SAMPLE)
    method = tree.sections[1]
    joined = " ".join(p.text for p in method.paragraphs)
    # The equation body itself shouldn't pollute paragraph text
    assert "y = mx + b" not in joined
    # But the surrounding prose should be present
    assert "linear model" in joined.lower()


def test_raw_source_preserved():
    tree = LaTeXParser().parse(SAMPLE)
    intro = tree.sections[0]
    p0 = intro.paragraphs[0]
    # raw_source must contain the original cite command verbatim
    assert r"\cite{smith2023, jones2024}" in p0.raw_source


def test_span_offsets_into_source():
    tree = LaTeXParser().parse(SAMPLE)
    for p in tree.all_paragraphs():
        sub = tree.source_text[p.span.start : p.span.end]
        assert sub == p.raw_source, f"span mismatch for {p.id}"


def test_stats_sane():
    tree = LaTeXParser().parse(SAMPLE)
    s = tree.stats()
    assert s["sections"] >= 4  # 3 top + 1 sub
    assert s["paragraphs"] >= 4
    assert s["words"] > 30
