"""LaTeX export.

Per user spec:
  * Only `accepted` (and `modified` -- treated as accepted-with-edit) are
    written into the output file as **plain-text replacements**. We do NOT
    wrap them in `\replaced{}` and do NOT inject the `changes` package --
    the exported .tex compiles cleanly without any extra LaTeX dependency.
  * Pending / rejected are NOT written. The caller (Web UI) MUST surface
    `summary.pending` so the user knows pending decisions are being
    discarded; the export does not silently lose them.
  * The original raw_source for the paragraph is preserved character-for-
    character outside the edited spans -- comments, custom macros, math,
    citations, labels all round-trip exactly.

Implementation strategy
-----------------------
We operate directly on the original `source_text` using the SourceSpan
offsets stored on each paragraph. We locate `before` inside that
paragraph's raw_source, convert to absolute offsets, and apply the edits
in **reverse order of appearance** so earlier offsets stay valid while
later splices are made.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from ..agents.schema import Suggestion
from ..ir import DocumentTree


@dataclass
class ExportSummary:
    written_path: str
    accepted: int = 0
    modified: int = 0
    pending: int = 0
    rejected: int = 0
    skipped_not_found: int = 0   # before-string not found inside paragraph span
    flagged_pending: list[str] = None  # ids of pending suggestions w/ flag_for_user

    def to_dict(self) -> dict:
        return {
            "written_path": self.written_path,
            "accepted": self.accepted,
            "modified": self.modified,
            "pending": self.pending,
            "rejected": self.rejected,
            "skipped_not_found": self.skipped_not_found,
            "flagged_pending": list(self.flagged_pending or []),
        }


class LaTeXExporter:
    def export(
        self,
        tree: DocumentTree,
        suggestions: Iterable[Suggestion],
        out_path: str,
    ) -> ExportSummary:
        if tree.source_type != "latex":
            raise ValueError("LaTeXExporter requires a LaTeX-parsed DocumentTree")

        suggestions = list(suggestions)
        summary = ExportSummary(written_path=out_path, flagged_pending=[])

        # Tally + gather effective edits (accepted + modified).
        effective: list[Suggestion] = []
        for s in suggestions:
            if s.status == "accepted":
                summary.accepted += 1
                effective.append(s)
            elif s.status == "modified":
                summary.modified += 1
                effective.append(s)
            elif s.status == "rejected":
                summary.rejected += 1
            else:  # pending
                summary.pending += 1
                if s.flag_for_user:
                    summary.flagged_pending.append(s.id)

        # Build a per-paragraph edit list, sorted by descending position
        # within the paragraph. This lets us safely splice without recomputing
        # offsets after each replacement.
        para_index = {p.id: p for p in tree.all_paragraphs()}

        # We mutate a list of characters representing source_text. The
        # offsets in SourceSpan reference `tree.source_text` directly.
        buf = list(tree.source_text)

        # Group edits by paragraph; sort by descending start within paragraph
        # so applying them in order doesn't shift earlier indices.
        per_para: dict[str, list[Suggestion]] = {}
        for s in effective:
            per_para.setdefault(s.paragraph_id, []).append(s)

        for pid, edits in per_para.items():
            para = para_index.get(pid)
            if para is None:
                # paragraph went away (parser changed) -> drop edit
                summary.skipped_not_found += len(edits)
                continue
            # find within paragraph raw_source the offset of each `before`,
            # convert to absolute offsets, then sort desc.
            located: list[tuple[int, int, Suggestion]] = []
            for s in edits:
                # Use modified text if user provided it
                after_text = s.user_modified_after if s.status == "modified" and s.user_modified_after else s.after
                idx = para.raw_source.find(s.before)
                if idx < 0:
                    summary.skipped_not_found += 1
                    continue
                abs_start = para.span.start + idx
                abs_end = abs_start + len(s.before)
                # build a synthetic with the resolved text
                resolved = Suggestion.from_dict(s.to_dict())
                resolved.after = after_text
                located.append((abs_start, abs_end, resolved))
            located.sort(key=lambda t: t[0], reverse=True)
            for abs_start, abs_end, s in located:
                # Plain-text replacement: substitute `before` with `after`
                # directly. No \replaced wrapper, no `changes` package, and
                # **no AI rationale comments** in the exported file. The
                # author's downstream artefact (.tex) must look like a
                # human-written manuscript; the AI's reasoning lives only in
                # the Web UI / decision log, never in what gets submitted.
                buf[abs_start:abs_end] = list(s.after)

        out = "".join(buf)

        with open(out_path, "w", encoding="utf-8") as f:
            f.write(out)
        return summary
