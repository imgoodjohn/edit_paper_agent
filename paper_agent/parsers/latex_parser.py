"""LaTeX -> DocumentTree.

Design choices
--------------
* We do NOT rely on TexSoup for the top-level structure walk because it
  silently drops malformed nodes and loses character offsets, which we
  need to round-trip edits back to the source file.

* Strategy:
    1. Locate the document body (between \\begin{document} and \\end{document}
       if present, else the whole file).
    2. Strip *content-irrelevant* environments (figure, table, equation,
       lstlisting, ...) but remember their spans so we can re-insert them.
    3. Walk sectioning commands (\\section / \\subsection / ...) in order
       and build a tree based on their levels.
    4. For each section's body, split into paragraphs on blank lines, then
       split paragraphs into sentences with a LaTeX-aware sentence splitter.

* `raw_source` on every Paragraph keeps the verbatim slice (including any
  inline math, citations, custom macros) so export can reconstruct the file.
"""
from __future__ import annotations

import hashlib
import re
from typing import Optional

from ..ir import DocumentTree, Paragraph, Section, Sentence, SourceSpan

# pylatexenc gives us a robust LaTeX -> text walker. We extend its macro DB
# with the `changes` package (\replaced/\added/\deleted) and the most common
# author-defined shortcuts seen in scientific papers.
try:
    from pylatexenc.latex2text import (
        LatexNodes2Text,
        MacroTextSpec,
        get_default_latex_context_db,
    )
    from pylatexenc.macrospec import MacroSpec

    _PLE_CTX = get_default_latex_context_db()
    _PLE_CTX.add_context_category(
        "paper_agent_extra",
        prepend=True,
        macros=[
            # changes package
            MacroSpec("replaced", "[{{"),  # [opt]{new}{old}
            MacroSpec("added", "[{"),
            MacroSpec("deleted", "[{"),
            # tracked-changes citing custom macros that often appear
            MacroSpec("jh", "{"),
            # sectioning we want to drop entirely (handled separately)
        ],
    )
    _PLE_CTX.add_context_category(
        "paper_agent_extra_text",
        prepend=True,
        macros=[
            MacroTextSpec("replaced", simplify_repl="%(1)s"),
            MacroTextSpec("added", simplify_repl="%(1)s"),
            MacroTextSpec("deleted", simplify_repl=""),
            MacroTextSpec("jh", simplify_repl="%(1)s"),
            MacroTextSpec("eg", simplify_repl="e.g."),
            MacroTextSpec("ie", simplify_repl="i.e."),
            MacroTextSpec("etc", simplify_repl="etc."),
            MacroTextSpec("etal", simplify_repl="et al."),
            MacroTextSpec("aka", simplify_repl="a.k.a."),
            MacroTextSpec("cite", simplify_repl="[CIT]"),
            MacroTextSpec("citep", simplify_repl="[CIT]"),
            MacroTextSpec("citet", simplify_repl="[CIT]"),
            MacroTextSpec("ref", simplify_repl="[REF]"),
            MacroTextSpec("eqref", simplify_repl="[REF]"),
            MacroTextSpec("autoref", simplify_repl="[REF]"),
            MacroTextSpec("cref", simplify_repl="[REF]"),
            MacroTextSpec("Cref", simplify_repl="[REF]"),
            MacroTextSpec("label", simplify_repl=""),
            MacroTextSpec("footnote", simplify_repl=""),
        ],
    )
    _PLE_NODES2TEXT = LatexNodes2Text(
        latex_context=_PLE_CTX,
        math_mode="verbatim",      # keep $...$ as-is
        keep_comments=False,
        strict_latex_spaces=False,
    )
    _HAS_PYLATEXENC = True
except Exception:  # pragma: no cover - fallback to regex flatten
    _PLE_NODES2TEXT = None
    _HAS_PYLATEXENC = False

# ---------------------------------------------------------------------------
# Regex tables
# ---------------------------------------------------------------------------

# \section{...} / \subsection*{...} / \subsubsection{...} / \paragraph{...}
SECTION_RE = re.compile(
    r"\\(?P<cmd>section|subsection|subsubsection|paragraph)\*?"
    r"\s*(?:\[[^\]]*\])?"  # optional short title
    r"\s*\{(?P<title>(?:[^{}]|\{[^{}]*\})*)\}",
    re.MULTILINE,
)

LEVEL = {"section": 1, "subsection": 2, "subsubsection": 3, "paragraph": 4}

# Environments whose textual content we don't feed to the language agent.
# We still record their spans so the exporter can preserve them verbatim.
SKIP_ENVS = (
    "figure",
    "figure*",
    "table",
    "table*",
    "equation",
    "equation*",
    "align",
    "align*",
    "gather",
    "gather*",
    "lstlisting",
    "verbatim",
    "minted",
    "tikzpicture",
    "algorithm",
    "algorithmic",
    "thebibliography",
)

BEGIN_DOC_RE = re.compile(r"\\begin\{document\}")
END_DOC_RE = re.compile(r"\\end\{document\}")
COMMENT_RE = re.compile(r"(?<!\\)%[^\n]*")
TITLE_RE = re.compile(r"\\title\s*\{((?:[^{}]|\{[^{}]*\})*)\}")
ABSTRACT_RE = re.compile(
    r"\\begin\{abstract\}(?P<body>.*?)\\end\{abstract\}", re.DOTALL
)
BIBITEM_RE = re.compile(r"\\bibitem(?:\[[^\]]*\])?\s*\{[^}]*\}\s*(?P<body>.*?)(?=\\bibitem|\\end\{thebibliography\}|$)", re.DOTALL)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hash_id(prefix: str, *parts: object) -> str:
    h = hashlib.md5("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:10]
    return f"{prefix}-{h}"


def _strip_for_text(latex: str) -> str:
    """Best-effort flatten of LaTeX -> human-readable text.

    Used only for the `text` field that LLMs read; the original `raw_source`
    is preserved separately for export.

    Uses pylatexenc when available (handles thousands of macros, math, lists,
    nested environments). Falls back to a regex flatten otherwise.
    """
    if _HAS_PYLATEXENC:
        try:
            out = _PLE_NODES2TEXT.latex_to_text(latex)
            # pylatexenc keeps unknown commands literal; collapse whitespace.
            out = re.sub(r"[ \t]+", " ", out)
            out = re.sub(r"\n{3,}", "\n\n", out)
            return out.strip()
        except Exception:
            # fall through to regex path on any parse error
            pass

    s = latex
    # Drop comments first
    s = COMMENT_RE.sub("", s)
    # `changes` package (tracked revisions): keep the *new* text, drop the rest.
    #   \replaced[opt]{new}{old} -> new
    #   \added[opt]{text}        -> text
    #   \deleted[opt]{text}      -> (empty)
    # Run iteratively to handle nested cases.
    for _ in range(3):
        prev = s
        s = re.sub(
            r"\\replaced\s*(?:\[(?:[^\[\]]|\[[^\]]*\])*\])?\s*"
            r"\{((?:[^{}]|\{[^{}]*\})*)\}\s*\{(?:[^{}]|\{[^{}]*\})*\}",
            r"\1",
            s,
        )
        s = re.sub(
            r"\\added\s*(?:\[(?:[^\[\]]|\[[^\]]*\])*\])?\s*\{((?:[^{}]|\{[^{}]*\})*)\}",
            r"\1",
            s,
        )
        s = re.sub(
            r"\\deleted\s*(?:\[(?:[^\[\]]|\[[^\]]*\])*\])?\s*\{(?:[^{}]|\{[^{}]*\})*\}",
            "",
            s,
        )
        if s == prev:
            break
    # Common inline replacements
    s = re.sub(r"\\(?:emph|textbf|textit|textsc|texttt|underline)\{([^{}]*)\}", r"\1", s)
    s = re.sub(r"\\(?:cite|citep|citet|ref|eqref|autoref|cref|Cref)\*?\s*(?:\[[^\]]*\])*\s*\{[^}]*\}", "[CIT]", s)
    s = re.sub(r"\\(?:label|index)\{[^}]*\}", "", s)
    s = re.sub(r"\\footnote\{(?:[^{}]|\{[^{}]*\})*\}", "", s)
    # Custom semantic shortcuts that often appear (\eg, \etal, etc.)
    s = re.sub(r"\\(?:eg|ie|etc|etal|aka)\b\.?", lambda m: {
        "\\eg": "e.g.", "\\ie": "i.e.", "\\etc": "etc.",
        "\\etal": "et al.", "\\aka": "a.k.a.",
    }.get(m.group(0).split('.')[0], m.group(0)), s)
    # Inline math: keep as $...$ marker (don't try to render)
    # Generic single-arg command fallback: \cmd{arg} -> arg (last resort)
    # Apply a few iterations to handle nested wrappers like \textbf{\emph{x}}
    for _ in range(3):
        s_new = re.sub(r"\\[a-zA-Z]+\*?\s*\{([^{}]*)\}", r"\1", s)
        if s_new == s:
            break
        s = s_new
    # Collapse whitespace
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


# Sentence boundary: punctuation followed by whitespace + capital/quote/[/(.
# Avoids splitting on common abbreviations and after \etal, e.g., i.e., Fig.
ABBREV = {"e.g", "i.e", "etc", "Fig", "fig", "Eq", "eq", "Sec", "sec", "Ref",
          "ref", "vs", "cf", "Dr", "Mr", "Mrs", "St", "et al", "Inc", "Ltd"}


def _split_sentences(text: str) -> list[tuple[str, int, int]]:
    """Return list of (sentence_text, start_offset, end_offset) within text."""
    if not text.strip():
        return []
    out: list[tuple[str, int, int]] = []
    n = len(text)
    start = 0
    i = 0
    while i < n:
        ch = text[i]
        if ch in ".!?":
            # peek next non-space
            j = i + 1
            while j < n and text[j] in ".!?\"')]}":
                j += 1
            if j >= n or text[j] in " \t\n":
                # check abbreviation
                back = text[max(0, i - 6):i]
                if any(back.endswith(a) for a in ABBREV):
                    i = j
                    continue
                # finalize sentence
                seg = text[start:j].strip()
                if seg:
                    # find true offsets ignoring leading whitespace
                    s_off = start + (len(text[start:j]) - len(text[start:j].lstrip()))
                    out.append((seg, s_off, j))
                # skip whitespace to next sentence start
                k = j
                while k < n and text[k] in " \t\n":
                    k += 1
                start = k
                i = k
                continue
        i += 1
    tail = text[start:].strip()
    if tail:
        s_off = start + (len(text[start:]) - len(text[start:].lstrip()))
        out.append((tail, s_off, n))
    return out


def _mask_skip_envs(src: str) -> str:
    """Replace \\begin{env}..\\end{env} bodies with same-length placeholders.

    This keeps character offsets intact so spans into the masked string also
    point into the original. Used so section-walking & paragraph-splitting
    don't dive into figure/equation guts.

    Also masks LaTeX comments (% to end-of-line) so commented-out section
    commands are not picked up as real sections.
    """
    masked = list(src)
    # Mask LaTeX line comments first: replace % ... \n with spaces (preserve \n)
    for m in COMMENT_RE.finditer(src):
        for k in range(m.start(), m.end()):
            masked[k] = " "
    # Mask skip environments
    for env in SKIP_ENVS:
        pat = re.compile(
            r"\\begin\{" + re.escape(env) + r"\}.*?\\end\{" + re.escape(env) + r"\}",
            re.DOTALL,
        )
        for m in pat.finditer(src):
            for k in range(m.start(), m.end()):
                # Preserve newlines so paragraph-splitting works around the block,
                # replace everything else with space.
                if masked[k] != "\n":
                    masked[k] = " "
    return "".join(masked)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class LaTeXParser:
    def parse(self, latex_src: str) -> DocumentTree:
        # 1) Locate body
        body_start, body_end = self._find_body_span(latex_src)

        # 2) Mask skip-envs (offsets preserved)
        masked = _mask_skip_envs(latex_src)

        # 3) Title / abstract / refs from full source
        title = self._extract_title(latex_src)
        abstract = self._extract_abstract(latex_src)
        references = self._extract_references(latex_src)

        # 4) Walk sections within body
        sections = self._build_sections(masked, latex_src, body_start, body_end)

        return DocumentTree(
            title=title,
            abstract=abstract,
            sections=sections,
            references=references,
            source_type="latex",
            source_text=latex_src,
            metadata={"body_start": body_start, "body_end": body_end},
        )

    # ------------------------------------------------------------------ body

    def _find_body_span(self, src: str) -> tuple[int, int]:
        b = BEGIN_DOC_RE.search(src)
        e = END_DOC_RE.search(src)
        start = b.end() if b else 0
        end = e.start() if e else len(src)
        return start, end

    # ------------------------------------------------------------------ title

    def _extract_title(self, src: str) -> str:
        m = TITLE_RE.search(src)
        if not m:
            return ""
        return _strip_for_text(m.group(1))

    # --------------------------------------------------------------- abstract

    def _extract_abstract(self, src: str) -> Optional[Paragraph]:
        m = ABSTRACT_RE.search(src)
        if not m:
            return None
        body = m.group("body")
        clean = _strip_for_text(body)
        sents = _split_sentences(clean)
        # span: offsets into original src
        start = m.start("body")
        end = m.end("body")
        sentences = [
            Sentence(
                id=_hash_id("abs-s", i, t[:32]),
                text=t,
                span=SourceSpan(start + so, start + eo),
            )
            for i, (t, so, eo) in enumerate(sents)
        ]
        return Paragraph(
            id=_hash_id("abs", body[:64]),
            kind="abstract",
            sentences=sentences,
            raw_source=body,
            span=SourceSpan(start, end),
        )

    # ------------------------------------------------------------- references

    def _extract_references(self, src: str) -> list[str]:
        out: list[str] = []
        for m in BIBITEM_RE.finditer(src):
            body = m.group("body").strip()
            if body:
                out.append(_strip_for_text(body))
        return out

    # ---------------------------------------------------------------- sections

    def _build_sections(
        self,
        masked: str,
        original: str,
        body_start: int,
        body_end: int,
    ) -> list[Section]:
        # collect section headers within body
        headers: list[dict] = []
        for m in SECTION_RE.finditer(masked, body_start, body_end):
            headers.append(
                {
                    "level": LEVEL[m.group("cmd")],
                    "title": _strip_for_text(m.group("title")),
                    "header_start": m.start(),
                    "header_end": m.end(),
                }
            )

        if not headers:
            return []

        # compute body span for each header (header_end .. next_header_start or body_end)
        for i, h in enumerate(headers):
            h["body_start"] = h["header_end"]
            h["body_end"] = headers[i + 1]["header_start"] if i + 1 < len(headers) else body_end

        # Build hierarchy by level
        roots: list[Section] = []
        stack: list[Section] = []
        for i, h in enumerate(headers):
            sec = Section(
                id=_hash_id("sec", i, h["title"]),
                level=h["level"],
                title=h["title"],
                span=SourceSpan(h["header_start"], h["body_end"]),
            )
            sec.paragraphs = self._extract_paragraphs(
                masked, original, h["body_start"], h["body_end"], sec.id
            )
            # find parent: nearest in stack with strictly smaller level
            while stack and stack[-1].level >= sec.level:
                stack.pop()
            if stack:
                stack[-1].children.append(sec)
            else:
                roots.append(sec)
            stack.append(sec)
        return roots

    # ------------------------------------------------------------- paragraphs

    def _extract_paragraphs(
        self,
        masked: str,
        original: str,
        start: int,
        end: int,
        section_id: str,
    ) -> list[Paragraph]:
        if start >= end:
            return []
        # split masked region on blank lines (>=2 newlines), but keep offsets
        region = masked[start:end]
        paragraphs: list[Paragraph] = []
        # iterate paragraph spans
        idx = 0
        para_idx = 0
        while idx < len(region):
            # skip leading whitespace
            while idx < len(region) and region[idx] in " \t\n":
                idx += 1
            if idx >= len(region):
                break
            # find next blank line
            m = re.search(r"\n[ \t]*\n", region[idx:])
            p_end = idx + m.start() if m else len(region)
            abs_start = start + idx
            abs_end = start + p_end
            raw = original[abs_start:abs_end]
            clean = _strip_for_text(raw)
            if clean and len(clean) >= 4:
                sents = _split_sentences(clean)
                # NOTE: sentence offsets here are into `clean`, not the original.
                # For v1 we map sentence span to the paragraph span (coarse).
                # Fine-grained mapping would require a clean<->raw alignment,
                # which we'll add when the editor actually needs sentence-level
                # in-place patching.
                sentences = [
                    Sentence(
                        id=_hash_id("s", section_id, para_idx, i, t[:24]),
                        text=t,
                        span=SourceSpan(abs_start, abs_end),
                    )
                    for i, (t, _so, _eo) in enumerate(sents)
                ]
                paragraphs.append(
                    Paragraph(
                        id=_hash_id("p", section_id, para_idx),
                        kind="body",
                        sentences=sentences,
                        raw_source=raw,
                        span=SourceSpan(abs_start, abs_end),
                        metadata={"section_id": section_id, "index": para_idx},
                    )
                )
                para_idx += 1
            idx = p_end
            # skip the blank line itself
            if m:
                idx += m.end() - m.start()
        return paragraphs
