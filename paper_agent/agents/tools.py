"""Tool implementations available to the ToolAgent.

Each function is pure: (DocumentTree, **kwargs) -> dict.
Results are JSON-serialisable and capped to avoid flooding the context window.
"""
from __future__ import annotations

import re
from typing import Optional

from ..ir import DocumentTree

MAX_TEXT = 3000   # chars per result before truncation


def get_toc(tree: DocumentTree) -> dict:
    """Return the table of contents with section ids, levels, and titles."""
    toc = tree.toc()
    return {"title": tree.title, "source_type": tree.source_type, "toc": toc}


def get_abstract(tree: DocumentTree) -> dict:
    """Return the abstract paragraph text."""
    if tree.abstract is None:
        return {"error": "No abstract found in document"}
    return {"paragraph_id": tree.abstract.id, "text": tree.abstract.text}


def get_references(tree: DocumentTree) -> dict:
    """Return the reference list (raw strings from the document)."""
    refs = tree.references
    return {"count": len(refs), "references": refs[:50]}


def get_section_list(tree: DocumentTree) -> dict:
    """List every section/subsection with its id and title."""
    sections = []
    for s in tree.sections:
        for sub in s.walk():
            sections.append({
                "id": sub.id,
                "level": sub.level,
                "title": sub.title,
                "n_paragraphs": len(list(sub.all_paragraphs())),
            })
    return {"sections": sections}


def read_section(tree: DocumentTree, section_id: str) -> dict:
    """Return full text of a section, paragraph by paragraph."""
    sec = tree.find_section(section_id)
    if sec is None:
        return {"error": f"section '{section_id}' not found"}
    paras = list(sec.all_paragraphs())
    lines = [f"[{p.id}|{p.kind}] {p.text}" for p in paras]
    text = "\n\n".join(lines)
    return {
        "section_id": section_id,
        "title": sec.title,
        "n_paragraphs": len(paras),
        "text": text[:MAX_TEXT],
        "truncated": len(text) > MAX_TEXT,
    }


def read_paragraph(tree: DocumentTree, paragraph_id: str) -> dict:
    """Get the full text of a specific paragraph."""
    p = tree.find_paragraph(paragraph_id)
    if p is None:
        return {"error": f"paragraph '{paragraph_id}' not found"}
    return {
        "paragraph_id": p.id,
        "kind": p.kind,
        "section_id": p.metadata.get("section_id", ""),
        "text": p.text,
    }


def search_text(
    tree: DocumentTree,
    query: str,
    case_sensitive: bool = False,
    is_regex: bool = False,
    section_id: Optional[str] = None,
) -> dict:
    """Search for a keyword or regex pattern across the document (or one section)."""
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        pat = re.compile(query if is_regex else re.escape(query), flags)
    except re.error as e:
        return {"error": f"Invalid pattern: {e}"}

    if section_id:
        sec = tree.find_section(section_id)
        source = list(sec.all_paragraphs()) if sec else []
    else:
        source = list(tree.all_paragraphs())

    matches: list[dict] = []
    for p in source:
        for m in pat.finditer(p.text):
            matches.append({
                "paragraph_id": p.id,
                "match": m.group()[:120],
                "context": p.text[max(0, m.start() - 60): m.end() + 60],
            })
            if len(matches) >= 30:
                break
        if len(matches) >= 30:
            break

    return {
        "query": query,
        "scope": section_id or "full_document",
        "total_matches": len(matches),
        "matches": matches,
    }


def get_lines(tree: DocumentTree, start_line: int, end_line: int) -> dict:
    """Return raw source lines by 1-based line number range."""
    lines = tree.source_text.splitlines()
    n = len(lines)
    s = max(0, start_line - 1)
    e = min(n, end_line)
    chunk = "\n".join(f"{s + i + 1}: {l}" for i, l in enumerate(lines[s:e]))
    return {
        "start_line": s + 1,
        "end_line": s + len(lines[s:e]),
        "total_lines": n,
        "text": chunk[:MAX_TEXT],
    }


def count_stats(
    tree: DocumentTree,
    scope: str = "full",
    section_id: Optional[str] = None,
    paragraph_id: Optional[str] = None,
) -> dict:
    """Count words (and optionally figures/tables) in the document or a specific part.

    scope: "full" | "abstract" | "references" | "section" | "paragraph"
      - "section"   requires section_id
      - "paragraph" requires paragraph_id
    """
    result: dict = {"scope": scope}

    if scope == "abstract":
        if tree.abstract is None:
            return {"scope": "abstract", "error": "No abstract found"}
        result["words"] = len(tree.abstract.text.split())
        result["paragraph_id"] = tree.abstract.id
        return result

    if scope == "references":
        result["count"] = len(tree.references)
        result["words"] = sum(len(r.split()) for r in tree.references)
        return result

    if scope == "section":
        sec = tree.find_section(section_id or "")
        if sec is None:
            return {"scope": "section", "error": f"Section '{section_id}' not found"}
        paras = list(sec.all_paragraphs())
        result["section_id"]    = sec.id
        result["section_title"] = sec.title
        result["words"]         = sum(len(p.text.split()) for p in paras)
        result["paragraphs"]    = len(paras)
        return result

    if scope == "paragraph":
        para = tree.find_paragraph(paragraph_id or "")
        if para is None:
            return {"scope": "paragraph", "error": f"Paragraph '{paragraph_id}' not found"}
        result["paragraph_id"] = para.id
        result["words"]        = len(para.text.split())
        return result

    # Default: full document
    n_words = sum(len(p.text.split()) for p in tree.all_paragraphs())
    src = tree.source_text
    if tree.source_type == "latex":
        n_figures = len(re.findall(r'\\begin\s*\{figure', src, re.IGNORECASE))
        n_tables  = len(re.findall(r'\\begin\s*\{table',  src, re.IGNORECASE))
    else:
        n_figures = sum(1 for p in tree.all_paragraphs() if "figure" in p.kind.lower())
        n_tables  = sum(1 for p in tree.all_paragraphs() if "table"  in p.kind.lower())
    # Per-section word counts
    sections = []
    for s in tree.sections:
        for sub in s.walk():
            w = sum(len(p.text.split()) for p in sub.paragraphs)
            if w > 0:
                sections.append({"id": sub.id, "title": sub.title, "words": w})
    abstract_words = len(tree.abstract.text.split()) if tree.abstract else 0
    return {
        "scope": "full",
        "total_words": n_words,
        "abstract_words": abstract_words,
        "body_words": n_words - abstract_words,
        "figures": n_figures,
        "tables": n_tables,
        "references": len(tree.references),
        "source_type": tree.source_type,
        "per_section": sections,
    }


def fetch_url(url: str) -> dict:
    """Fetch a web page (journal guidelines, citation formats, etc.)."""
    try:
        import httpx
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
        }
        resp = httpx.get(url, timeout=15, follow_redirects=True, headers=headers)
        text = re.sub(r"<script[^>]*>.*?</script>", " ", resp.text, flags=re.DOTALL)
        text = re.sub(r"<style[^>]*>.*?</style>",  " ", text, flags=re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return {"url": url, "status": resp.status_code, "text": text[:MAX_TEXT]}
    except Exception as e:
        return {"url": url, "error": str(e)}
