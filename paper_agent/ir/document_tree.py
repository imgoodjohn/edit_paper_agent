"""Unified Intermediate Representation for parsed papers.

A DocumentTree is a hierarchy: DocumentTree -> Section* -> Paragraph* -> Sentence*.
Every node retains:
  - a stable id (for cross-referencing review comments)
  - raw_source (verbatim original LaTeX/XML chunk; required for re-emission)
  - SourceSpan (character offsets into the original source string)

Why we keep both `text` (clean) and `raw_source` (with markup):
  - Agents read `text` so they don't get distracted by LaTeX commands.
  - Export reconstructs the file using `raw_source` + accepted edits,
    so we can produce a faithful patched LaTeX/DOCX.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator, Optional


@dataclass
class SourceSpan:
    """Character offsets into the original source string.

    `start` is inclusive, `end` is exclusive (Python slice semantics).
    For DOCX inputs `start`/`end` index into a deterministically rebuilt
    plain-text projection (see word_parser).
    """

    start: int
    end: int

    def slice(self, source: str) -> str:
        return source[self.start : self.end]


@dataclass
class Sentence:
    id: str
    text: str
    span: SourceSpan

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("Sentence.id must be non-empty")


@dataclass
class Paragraph:
    id: str
    # "abstract" | "body" | "caption" | "list_item"
    kind: str
    sentences: list[Sentence]
    raw_source: str
    span: SourceSpan
    metadata: dict = field(default_factory=dict)

    @property
    def text(self) -> str:
        return " ".join(s.text for s in self.sentences)


@dataclass
class Section:
    id: str
    level: int  # 1=section, 2=subsection, 3=subsubsection, 4=paragraph
    title: str
    paragraphs: list[Paragraph] = field(default_factory=list)
    children: list["Section"] = field(default_factory=list)
    span: Optional[SourceSpan] = None
    metadata: dict = field(default_factory=dict)

    def walk(self) -> Iterator["Section"]:
        yield self
        for c in self.children:
            yield from c.walk()

    def all_paragraphs(self) -> Iterator[Paragraph]:
        for s in self.walk():
            yield from s.paragraphs


@dataclass
class DocumentTree:
    title: str
    abstract: Optional[Paragraph]
    sections: list[Section]
    references: list[str]
    source_type: str  # "latex" | "docx"
    source_text: str  # original full source (or rebuilt projection for docx)
    metadata: dict = field(default_factory=dict)

    # ---- convenience accessors ------------------------------------------------

    def toc(self) -> list[dict]:
        out: list[dict] = []
        for s in self.sections:
            for sub in s.walk():
                out.append(
                    {
                        "id": sub.id,
                        "level": sub.level,
                        "title": sub.title,
                    }
                )
        return out

    def all_paragraphs(self) -> Iterator[Paragraph]:
        if self.abstract is not None:
            yield self.abstract
        for s in self.sections:
            yield from s.all_paragraphs()

    def find_paragraph(self, paragraph_id: str) -> Optional[Paragraph]:
        for p in self.all_paragraphs():
            if p.id == paragraph_id:
                return p
        return None

    def find_section(self, section_id: str) -> Optional[Section]:
        for s in self.sections:
            for sub in s.walk():
                if sub.id == section_id:
                    return sub
        return None

    def stats(self) -> dict:
        n_sec = sum(1 for _ in (sub for s in self.sections for sub in s.walk()))
        n_par = sum(1 for _ in self.all_paragraphs())
        n_sent = sum(len(p.sentences) for p in self.all_paragraphs())
        n_words = sum(len(p.text.split()) for p in self.all_paragraphs())
        return {
            "sections": n_sec,
            "paragraphs": n_par,
            "sentences": n_sent,
            "words": n_words,
            "references": len(self.references),
        }
