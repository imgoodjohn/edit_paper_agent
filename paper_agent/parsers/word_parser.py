"""DOCX -> DocumentTree.

Strategy
--------
* Uses python-docx to walk paragraphs in document order.
* A paragraph whose style name starts with "Heading <N>" becomes a Section
  at level N. All non-heading paragraphs are appended to the current
  innermost section (or to a synthetic "Body" root if no heading seen yet).
* Source offsets index into a deterministically rebuilt plain-text projection
  of the document (one paragraph per line, blank line between). The exporter
  uses paragraph indices, not character offsets, to apply edits.
"""
from __future__ import annotations

import hashlib
import re
from typing import Optional

from ..ir import DocumentTree, Paragraph, Section, Sentence, SourceSpan
from .latex_parser import _split_sentences  # reuse


def _hash_id(prefix: str, *parts: object) -> str:
    h = hashlib.md5("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:10]
    return f"{prefix}-{h}"


_HEADING_RE = re.compile(r"^Heading\s+(\d+)$", re.IGNORECASE)


class WordParser:
    def parse_file(self, path: str) -> DocumentTree:
        try:
            from docx import Document  # python-docx
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "python-docx is required for WordParser. Install with `pip install python-docx`."
            ) from e

        doc = Document(path)
        return self._parse_doc(doc)

    def _parse_doc(self, doc) -> DocumentTree:
        # Build a plain-text projection so we can give every node a SourceSpan.
        projection_chunks: list[str] = []
        offsets: list[int] = []  # per-paragraph start offset in projection
        running = 0
        para_texts: list[tuple[Optional[int], str, str]] = []  # (heading_level, style, text)

        for p in doc.paragraphs:
            style = (p.style.name or "") if p.style else ""
            m = _HEADING_RE.match(style)
            level = int(m.group(1)) if m else None
            text = p.text or ""
            offsets.append(running)
            projection_chunks.append(text)
            running += len(text) + 2  # account for "\n\n" separator
            para_texts.append((level, style, text))

        projection = "\n\n".join(projection_chunks)

        title = ""
        # Heuristic: first non-empty paragraph styled "Title" or first heading-1
        for level, style, text in para_texts:
            if not text.strip():
                continue
            if style.lower() == "title" or level == 1:
                title = text.strip()
                break

        abstract: Optional[Paragraph] = None
        sections: list[Section] = []
        stack: list[Section] = []
        in_abstract = False
        para_counter = 0

        for idx, ((level, style, text), abs_start) in enumerate(
            zip(para_texts, offsets)
        ):
            abs_end = abs_start + len(text)
            stripped = text.strip()
            if not stripped:
                continue

            # Section heading
            if level is not None:
                sec = Section(
                    id=_hash_id("sec", idx, stripped),
                    level=level,
                    title=stripped,
                    span=SourceSpan(abs_start, abs_end),
                )
                while stack and stack[-1].level >= level:
                    stack.pop()
                if stack:
                    stack[-1].children.append(sec)
                else:
                    sections.append(sec)
                stack.append(sec)
                in_abstract = stripped.lower().startswith("abstract")
                continue

            # Paragraph body
            sents = _split_sentences(stripped)
            sentences = [
                Sentence(
                    id=_hash_id("s", idx, i, t[:24]),
                    text=t,
                    span=SourceSpan(abs_start, abs_end),
                )
                for i, (t, _so, _eo) in enumerate(sents)
            ]
            kind = "abstract" if in_abstract else "body"
            para = Paragraph(
                id=_hash_id("p", idx, para_counter),
                kind=kind,
                sentences=sentences,
                raw_source=text,
                span=SourceSpan(abs_start, abs_end),
                metadata={"docx_index": idx, "style": style},
            )
            para_counter += 1

            if in_abstract and abstract is None:
                abstract = para
                continue
            if stack:
                stack[-1].paragraphs.append(para)
            else:
                # No heading yet -> create synthetic root "Body"
                if not sections:
                    root = Section(
                        id=_hash_id("sec", "root"),
                        level=1,
                        title="Body",
                        span=SourceSpan(abs_start, abs_end),
                    )
                    sections.append(root)
                    stack.append(root)
                stack[-1].paragraphs.append(para)

        return DocumentTree(
            title=title,
            abstract=abstract,
            sections=sections,
            references=[],
            source_type="docx",
            source_text=projection,
            metadata={"docx_paragraph_count": len(para_texts)},
        )
