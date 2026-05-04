"""DOCX export with native Word Track Changes.

Per user spec:
  * `accepted` / `modified` -> applied as plain text replacements (the user
    has already adjudicated these in the web UI; no track-change marks).
  * `pending` -> written as Word revisions:
        <w:del w:author="...">before</w:del>
        <w:ins w:author="...">after</w:ins>
    so that when the user opens the .docx in Word / LibreOffice they see
    track-change marks and can accept/reject natively in their editor.
  * `rejected` -> not written (original text preserved).
  * The `author` shown on every revision is user-configurable. The UI lets
    the user pick whose name appears on the track changes (default
    "Paper-Agent AI", but a logged-in user can use their own name).
  * Adjudicated edits (accepted / modified) are **clean of AI metadata**
    -- the user has decided, so the manuscript looks human-edited.
  * Pending edits ALSO get a Word comment (in `word/comments.xml`) anchored
    on the inserted text. The comment is `[<category>/<severity>] <rationale>`
    so the author opens the .docx and sees the AI's reasoning in the
    Comments pane next to each unresolved revision -- exactly the UX a
    peer reviewer would leave.

We work directly on the docx XML because python-docx has no first-class
track-changes API. We open the docx, walk paragraphs in order, and for
each paragraph that has matching suggestions we replace the run text with
the appropriate <w:r>/<w:ins>/<w:del> sequence.

The implementation is intentionally minimal -- it handles the common case
(one paragraph = one run with the entire text). For documents with mixed
formatting inside a paragraph (multiple runs) we fall back to flattening
the runs into one before applying revisions; formatting may be lost in
the affected paragraph. This is acceptable for an MVP and is exactly the
trade-off the user asked for ("if user does not accept/decline, write as
revision mode and let them deal with it in Word").
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from ..agents.schema import Suggestion
from ..ir import DocumentTree
from .latex_exporter import ExportSummary


# Word XML namespace (constant across modern .docx files)
_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _qn(tag: str) -> str:
    return f"{{{_W_NS}}}{tag}"


class DocxExporter:
    def export(
        self,
        tree: DocumentTree,
        suggestions: Iterable[Suggestion],
        source_docx_path: str,
        out_path: str,
        author: str = "Paper-Agent AI",
    ) -> ExportSummary:
        if tree.source_type != "docx":
            raise ValueError("DocxExporter requires a docx-parsed DocumentTree")

        try:
            from docx import Document
            from docx.oxml.ns import nsmap
            from lxml import etree  # python-docx ships with lxml
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("python-docx is required for DocxExporter") from e

        suggestions = list(suggestions)
        summary = ExportSummary(written_path=out_path, flagged_pending=[])

        # Tally
        for s in suggestions:
            if s.status == "accepted":
                summary.accepted += 1
            elif s.status == "modified":
                summary.modified += 1
            elif s.status == "rejected":
                summary.rejected += 1
            else:
                summary.pending += 1
                if s.flag_for_user:
                    summary.flagged_pending.append(s.id)

        # Map: docx-paragraph index -> list of suggestions
        per_para: dict[int, list[Suggestion]] = {}
        for p in tree.all_paragraphs():
            idx = p.metadata.get("docx_index")
            if idx is None:
                continue
            for s in suggestions:
                if s.paragraph_id == p.id and s.status != "rejected":
                    per_para.setdefault(idx, []).append(s)

        doc = Document(source_docx_path)
        comments_writer = _CommentsWriter(doc, author)
        rev_id = 1000  # arbitrary starting w:id

        for idx, paragraph in enumerate(doc.paragraphs):
            edits = per_para.get(idx)
            if not edits:
                continue

            full_text = paragraph.text
            # Apply each suggestion sequentially to a working text.
            # We track segments: (kind, text, suggestion?) where kind in
            #   "keep" | "ins" | "del". The suggestion is attached to ins/del
            # segments so we can hang a Word comment on each edit.
            segments: list[tuple[str, str, object]] = [("keep", full_text, None)]

            for s in edits:
                segments = _apply_edit(segments, s)
            self._rewrite_paragraph(paragraph, segments, rev_id, author, comments_writer)
            rev_id += 50

        comments_writer.finalize()
        doc.save(out_path)
        return summary

    @staticmethod
    def _rewrite_paragraph(paragraph, segments, rev_id_start: int, author: str,
                           comments_writer) -> None:
        from lxml import etree

        # Drop existing runs (preserves paragraph properties pPr).
        p_elem = paragraph._p
        for r in list(p_elem):
            tag = etree.QName(r).localname
            if tag in ("r", "ins", "del", "commentRangeStart", "commentRangeEnd"):
                p_elem.remove(r)

        rev_id = rev_id_start
        date = "2026-01-01T00:00:00Z"

        for kind, text, sugg in segments:
            if not text and kind != "keep":
                continue
            if kind == "keep":
                if not text:
                    continue
                # An "accepted" replacement is also kind="keep" but carries
                # the originating suggestion so we can attach a comment.
                cid = comments_writer.add(sugg) if sugg is not None else None
                if cid is not None:
                    p_elem.append(_make_comment_range_marker("commentRangeStart", cid))
                p_elem.append(_make_run(text))
                if cid is not None:
                    p_elem.append(_make_comment_range_marker("commentRangeEnd", cid))
                    p_elem.append(_make_comment_reference_run(cid))
            elif kind == "ins":
                # Wrap the inserted run in a Word comment range so the AI's
                # rationale shows up in the Comments pane on the new text.
                cid = comments_writer.add(sugg) if sugg is not None else None
                if cid is not None:
                    p_elem.append(_make_comment_range_marker("commentRangeStart", cid))
                ins = etree.SubElement(p_elem, _qn("ins"))
                ins.set(_qn("id"), str(rev_id))
                ins.set(_qn("author"), author)
                ins.set(_qn("date"), date)
                ins.append(_make_run(text))
                rev_id += 1
                if cid is not None:
                    p_elem.append(_make_comment_range_marker("commentRangeEnd", cid))
                    p_elem.append(_make_comment_reference_run(cid))
            elif kind == "del":
                d = etree.SubElement(p_elem, _qn("del"))
                d.set(_qn("id"), str(rev_id))
                d.set(_qn("author"), author)
                d.set(_qn("date"), date)
                d.append(_make_run(text, deleted=True))
                rev_id += 1


def _make_run(text: str, deleted: bool = False):
    from lxml import etree

    r = etree.Element(_qn("r"))
    t_tag = "delText" if deleted else "t"
    t = etree.SubElement(r, _qn(t_tag))
    # preserve leading/trailing spaces
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    t.text = text
    return r


def _apply_edit(
    segments: list[tuple[str, str, object]], s: Suggestion
) -> list[tuple[str, str, object]]:
    """Splice a single suggestion into the segment list.

    Each segment is `(kind, text, sugg_or_None)`. The originating Suggestion
    is attached to ins/del/accepted-replacement segments so the rewrite step
    can hang a Word comment carrying the AI rationale on each one.

    The `before` substring is searched ONLY inside `keep` segments with
    `sugg is None` (we don't re-edit text already marked as ins/del or
    already adjudicated as another accepted edit).

    Status mapping:
      accepted / modified -> replace inline as a clean run; segment is
                             `("keep", new, None)`. The exported document
                             carries NO AI metadata for adjudicated edits --
                             the user has already decided, so the rationale
                             belongs in the Web UI / decision log, not in
                             the manuscript.
      pending             -> write as <del>old</del><ins>new</ins> Word
                             revisions, with the suggestion attached to the
                             <ins> side ONLY. The ins segment will be wrapped
                             in a Word comment range carrying the AI's
                             rationale -- so when the user opens the .docx
                             in Word they see the track-change AND a comment
                             explaining why the AI proposed it, exactly the
                             UX a peer reviewer would leave.
    """
    out: list[tuple[str, str, object]] = []
    matched = False
    after_text = (
        s.user_modified_after
        if s.status == "modified" and s.user_modified_after
        else s.after
    )
    for kind, text, owner in segments:
        if matched or kind != "keep" or owner is not None:
            out.append((kind, text, owner))
            continue
        idx = text.find(s.before)
        if idx < 0:
            out.append((kind, text, owner))
            continue
        prefix = text[:idx]
        suffix = text[idx + len(s.before) :]
        if prefix:
            out.append(("keep", prefix, None))

        if s.status in ("accepted", "modified"):
            # Adjudicated -> clean replacement, no comment attachment.
            if after_text:
                out.append(("keep", after_text, None))
        else:
            # Pending -> track changes + comment on the inserted run.
            if s.before:
                # Don't tag the deletion: a single comment per edit is
                # cleaner in the Word Comments pane.
                out.append(("del", s.before, None))
            if after_text:
                out.append(("ins", after_text, s))

        if suffix:
            out.append(("keep", suffix, None))
        matched = True
    return out


# ---------------------------------------------------------------------------
# Word comments writer
# ---------------------------------------------------------------------------

_COMMENTS_PART_NAME = "/word/comments.xml"
_COMMENTS_CT = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"
)
_COMMENTS_REL = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments"
)


def _make_comment_range_marker(local_name: str, cid: int):
    from lxml import etree

    el = etree.Element(_qn(local_name))
    el.set(_qn("id"), str(cid))
    return el


def _make_comment_reference_run(cid: int):
    from lxml import etree

    r = etree.Element(_qn("r"))
    rPr = etree.SubElement(r, _qn("rPr"))
    style = etree.SubElement(rPr, _qn("rStyle"))
    style.set(_qn("val"), "CommentReference")
    ref = etree.SubElement(r, _qn("commentReference"))
    ref.set(_qn("id"), str(cid))
    return r


class _CommentsWriter:
    """Lazily creates `word/comments.xml` and registers it on the package.

    `add(suggestion)` returns the `w:id` to use for the comment range, or
    `None` if there is nothing meaningful to say (no rationale).
    `finalize()` flushes the part into the .docx package.
    """

    def __init__(self, doc, author: str) -> None:
        self.doc = doc
        self.author = author
        self.next_id = 0
        from lxml import etree

        self._etree = etree
        self._comments_root = etree.Element(
            _qn("comments"),
            nsmap={"w": _W_NS},
        )
        self._dirty = False

    def add(self, sugg: Suggestion) -> int | None:
        """Add a Word comment carrying the AI rationale.

        Only invoked for **pending** suggestions (callers attach the
        suggestion to an `ins` segment only when status == 'pending'). For
        accepted / modified edits the segment carries `None` and we never
        get here, keeping the adjudicated text clean.

        Returns `None` if the rationale is empty (skip the comment markers
        entirely so we don't pollute the doc with empty comments).
        """
        text = (sugg.rationale or "").strip()
        if not text:
            return None
        if len(text) > 1500:
            text = text[:1500] + "…"
        cid = self.next_id
        self.next_id += 1

        c = self._etree.SubElement(self._comments_root, _qn("comment"))
        c.set(_qn("id"), str(cid))
        c.set(_qn("author"), self.author)
        c.set(_qn("initials"), "AI")
        c.set(_qn("date"), "2026-01-01T00:00:00Z")
        # Tag the rationale so the Word reader sees the category/severity
        # at a glance: "[grammar/info] Subject-verb agreement…".
        prefix = f"[{sugg.category}/{sugg.severity}] "
        body = self._etree.SubElement(c, _qn("p"))
        run = self._etree.SubElement(body, _qn("r"))
        t = self._etree.SubElement(run, _qn("t"))
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        t.text = prefix + text
        self._dirty = True
        return cid

    def finalize(self) -> None:
        """Flush `word/comments.xml` into the package if any comments were
        added. No-op when no pending suggestions had a rationale."""
        if not self._dirty:
            return
        from docx.opc.part import Part
        from docx.opc.packuri import PackURI

        xml_bytes = self._etree.tostring(
            self._comments_root,
            xml_declaration=True,
            encoding="UTF-8",
            standalone=True,
        )
        pkg = self.doc.part.package
        partname = PackURI(_COMMENTS_PART_NAME)
        # Replace any existing comments part (rare in our generated docs)
        # rather than registering a duplicate.
        existing = None
        for p in pkg.iter_parts():
            if p.partname == partname:
                existing = p
                break
        if existing is not None:
            existing._blob = xml_bytes
            return
        part = Part(partname, _COMMENTS_CT, xml_bytes, pkg)
        # Word only loads comments.xml when the main document part has a
        # relationship pointing at it.
        self.doc.part.relate_to(part, _COMMENTS_REL)
