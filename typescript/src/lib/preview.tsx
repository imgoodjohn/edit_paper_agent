'use client'

// Document preview renderer.
//
// LaTeX documents:
//   * The backend returns a list of structured blocks (heading | paragraph |
//     abstract). We render them as semantic HTML.
//   * Inline math `$...$` and display math `$$...$$` are rendered with KaTeX.
//   * `\cite{}`, `\ref{}`, `\label{}` etc. were already stripped server-side
//     by pylatexenc.
//   * Each paragraph gets a `data-paragraph-id` attribute so suggestion
//     overlays can be attached. Clicking an annotated paragraph opens an
//     inline review panel with accept / reject / modify controls.
//
// DOCX documents:
//   * Use mammoth.js to convert the .docx binary to HTML on the client.
//   * The mammoth output does not preserve paragraph ids, so we cannot
//     overlay per-paragraph suggestion markers there.

import { useEffect, useMemo, useState } from 'react'
import katex from 'katex'
import { API_BASE, type Suggestion } from '@/lib/api'

// -----------------------------------------------------------------------------
// LaTeX-style block list (used when source_type === 'latex')
// -----------------------------------------------------------------------------

export type PreviewBlock =
  | { kind: 'abstract'; id: string; text: string; raw?: string }
  | { kind: 'heading'; id: string; level: number; title: string }
  | { kind: 'paragraph'; id: string; section_id: string; text: string; raw?: string }

const MATH_BLOCK_RE = /\$\$([\s\S]+?)\$\$/g
const MATH_INLINE_RE = /\$([^$\n]+?)\$/g

function renderMath(tex: string, displayMode: boolean): string {
  try {
    return katex.renderToString(tex, {
      throwOnError: false,
      displayMode,
      strict: 'ignore',
    })
  } catch {
    return `<code>${escapeHtml(tex)}</code>`
  }
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function renderTextWithMath(text: string): string {
  // Replace $$...$$ first (display), then $...$ (inline).
  let out = ''
  let last = 0
  const blocks: { start: number; end: number; html: string }[] = []
  for (const m of text.matchAll(MATH_BLOCK_RE)) {
    blocks.push({
      start: m.index!,
      end: m.index! + m[0].length,
      html: renderMath(m[1], true),
    })
  }
  // Walk in order: append non-math escaped, append math html, then handle
  // inline math inside the remaining segments.
  for (const b of blocks) {
    out += inlineSplit(text.slice(last, b.start))
    out += b.html
    last = b.end
  }
  out += inlineSplit(text.slice(last))
  return out
}

function inlineSplit(text: string): string {
  let out = ''
  let last = 0
  for (const m of text.matchAll(MATH_INLINE_RE)) {
    out += escapeHtml(text.slice(last, m.index!))
    out += renderMath(m[1], false)
    last = m.index! + m[0].length
  }
  out += escapeHtml(text.slice(last))
  return out
}

// -----------------------------------------------------------------------------
// Word-level diff (for inline suggestion display)
// -----------------------------------------------------------------------------

type DiffToken = { type: 'eq' | 'del' | 'ins'; text: string }

function _lcs(a: string[], b: string[]): number[][] {
  const m = a.length, n = b.length
  const dp = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0))
  for (let i = 1; i <= m; i++)
    for (let j = 1; j <= n; j++)
      dp[i][j] = a[i-1] === b[j-1] ? dp[i-1][j-1] + 1 : Math.max(dp[i-1][j], dp[i][j-1])
  return dp
}

function wordDiff(before: string, after: string): DiffToken[] {
  if (before.length > 2000 || after.length > 2000)
    return [{ type: 'del', text: before }, { type: 'ins', text: after }]
  const a = before.match(/\S+|\s+/g) ?? []
  const b = after.match(/\S+|\s+/g) ?? []
  const dp = _lcs(a, b)
  const ops: DiffToken[] = []
  let i = a.length, j = b.length
  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && a[i-1] === b[j-1]) { ops.unshift({ type: 'eq', text: a[i-1] }); i--; j-- }
    else if (j > 0 && (i === 0 || dp[i][j-1] >= dp[i-1][j])) { ops.unshift({ type: 'ins', text: b[j-1] }); j-- }
    else { ops.unshift({ type: 'del', text: a[i-1] }); i-- }
  }
  return ops
}

function WordDiff({ before, after }: { before: string; after: string }) {
  const ops = wordDiff(before, after)
  return (
    <div className="whitespace-pre-wrap font-mono text-xs leading-relaxed">
      {ops.map((op, i) => {
        if (op.type === 'eq') return <span key={i}>{op.text}</span>
        if (op.type === 'del') return <span key={i} className="bg-red-100 text-red-700 line-through dark:bg-red-900/30 dark:text-red-400">{op.text}</span>
        return <span key={i} className="bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400">{op.text}</span>
      })}
    </div>
  )
}

// -----------------------------------------------------------------------------
// Inline suggestion row (shown inside expanded ParagraphBlock)
// -----------------------------------------------------------------------------

function InlineSuggestionRow(props: {
  s: Suggestion
  onDecide?: (id: string, d: 'accepted' | 'rejected' | 'modified', after?: string) => void
  busy?: string | null
}) {
  const { s, onDecide, busy } = props
  const [editing, setEditing] = useState(false)
  const [edited, setEdited] = useState(s.user_modified_after ?? s.after)
  const pending = s.status === 'pending'
  const statusColor = s.status === 'accepted' ? 'text-emerald-600' : s.status === 'rejected' ? 'text-red-500' : 'text-amber-600'
  return (
    <div className="rounded-md border border-zinc-200 bg-zinc-50 p-2.5 text-xs dark:border-zinc-700 dark:bg-zinc-800">
      <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
        <span className={`rounded px-1.5 py-0.5 font-semibold ${statusColor} bg-zinc-100 dark:bg-zinc-700`}>{s.status}</span>
        <span className="rounded bg-blue-100 px-1.5 py-0.5 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300">{s.category}</span>
        {s.flag_for_user && <span className="rounded bg-red-100 px-1.5 py-0.5 text-red-700 dark:bg-red-900/30 dark:text-red-300">⚠ numbers/cites</span>}
        <span className="ml-auto text-zinc-400">{s.severity}</span>
      </div>
      <WordDiff before={s.before} after={editing ? edited : (s.user_modified_after ?? s.after)} />
      <p className="mt-1.5 text-zinc-500 italic">{s.rationale}</p>
      {editing && (
        <textarea
          className="mt-1.5 w-full rounded border border-zinc-300 bg-white px-2 py-1 text-xs dark:border-zinc-600 dark:bg-zinc-900"
          rows={3}
          value={edited}
          onChange={e => setEdited(e.target.value)}
        />
      )}
      {pending && onDecide && (
        <div className="mt-2 flex flex-wrap gap-1.5" onClick={e => e.stopPropagation()}>
          <button
            className="rounded bg-emerald-600 px-2.5 py-0.5 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-40"
            disabled={!!busy}
            onClick={() => onDecide(s.id, 'accepted')}
          >✓ Accept</button>
          <button
            className="rounded bg-red-600 px-2.5 py-0.5 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-40"
            disabled={!!busy}
            onClick={() => onDecide(s.id, 'rejected')}
          >✗ Reject</button>
          {editing ? (
            <>
              <button
                className="rounded bg-emerald-600 px-2.5 py-0.5 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-40"
                disabled={!!busy}
                onClick={() => { onDecide(s.id, 'modified', edited); setEditing(false) }}
              >Save</button>
              <button
                className="rounded border border-zinc-300 px-2.5 py-0.5 text-xs font-medium hover:bg-zinc-100 dark:border-zinc-600 dark:hover:bg-zinc-700"
                onClick={() => setEditing(false)}
              >Cancel</button>
            </>
          ) : (
            <button
              className="rounded border border-zinc-300 px-2.5 py-0.5 text-xs font-medium hover:bg-zinc-100 dark:border-zinc-600 dark:hover:bg-zinc-700"
              onClick={() => setEditing(true)}
            >✎ Modify</button>
          )}
        </div>
      )}
    </div>
  )
}

// -----------------------------------------------------------------------------
// LaTeX preview (client renders the structured block list)
// -----------------------------------------------------------------------------

export function LatexPreview(props: {
  blocks: PreviewBlock[]
  suggestionsByParagraph: Record<string, Suggestion[]>
  focusedPid: string | null
  onParagraphClick: (paragraphId: string) => void
  onDecide?: (id: string, d: 'accepted' | 'rejected' | 'modified', after?: string) => void
  busy?: string | null
}) {
  return (
    <div className="prose prose-zinc max-w-none dark:prose-invert">
      {props.blocks.map((b, i) => {
        if (b.kind === 'abstract') {
          return (
            <ParagraphBlock
              key={`abs-${i}`}
              pid={b.id}
              text={b.text}
              kind="abstract"
              suggestions={props.suggestionsByParagraph[b.id] ?? []}
              focused={props.focusedPid === b.id}
              onToggle={props.onParagraphClick}
              onDecide={props.onDecide}
              busy={props.busy}
            />
          )
        }
        if (b.kind === 'heading') {
          const Tag = (`h${Math.min(b.level + 1, 4)}` as 'h2' | 'h3' | 'h4')
          return (
            <Tag key={b.id} className="!mt-8 !mb-2 scroll-mt-20" id={b.id}>
              {b.title}
            </Tag>
          )
        }
        return (
          <ParagraphBlock
            key={b.id}
            pid={b.id}
            text={b.text}
            kind="body"
            suggestions={props.suggestionsByParagraph[b.id] ?? []}
            focused={props.focusedPid === b.id}
            onToggle={props.onParagraphClick}
            onDecide={props.onDecide}
            busy={props.busy}
          />
        )
      })}
    </div>
  )
}

function ParagraphBlock(props: {
  pid: string
  text: string
  kind: 'abstract' | 'body'
  suggestions: Suggestion[]
  focused: boolean
  onToggle: (pid: string) => void
  onDecide?: (id: string, d: 'accepted' | 'rejected' | 'modified', after?: string) => void
  busy?: string | null
}) {
  const html = useMemo(() => renderTextWithMath(props.text), [props.text])
  const n = props.suggestions.length
  const nFlagged = props.suggestions.filter((s) => s.flag_for_user).length
  const nPending = props.suggestions.filter((s) => s.status === 'pending').length
  const ringClass =
    n === 0 ? ''
    : nFlagged > 0 ? 'ring-2 ring-red-300 dark:ring-red-500/40'
    : nPending > 0 ? 'ring-2 ring-amber-300 dark:ring-amber-500/40'
    : 'ring-2 ring-emerald-300 dark:ring-emerald-500/40'
  return (
    <div
      className={`group relative my-3 rounded-md p-2 transition ${ringClass} ${
        props.kind === 'abstract' ? 'border-l-4 border-zinc-400 bg-zinc-50 dark:bg-zinc-900/50' : ''
      } ${n > 0 ? 'cursor-pointer hover:bg-zinc-50 dark:hover:bg-zinc-900/50' : ''} ${
        props.focused ? 'bg-zinc-50 dark:bg-zinc-900/50' : ''
      }`}
      data-paragraph-id={props.pid}
      onClick={() => n > 0 && props.onToggle(props.pid)}
    >
      <p dangerouslySetInnerHTML={{ __html: html }} />
      {n > 0 ? (
        <div className="absolute right-2 top-2 flex gap-1 text-[10px] font-medium">
          <span className="rounded bg-zinc-200 px-1.5 py-0.5 dark:bg-zinc-700">
            {n} edit{n === 1 ? '' : 's'}
          </span>
          {nFlagged > 0 ? (
            <span className="rounded bg-red-200 px-1.5 py-0.5 text-red-900 dark:bg-red-700 dark:text-red-50">⚠ {nFlagged}</span>
          ) : null}
        </div>
      ) : null}
      {props.focused && n > 0 ? (
        <div
          className="mt-3 space-y-2 border-t border-zinc-200 pt-3 dark:border-zinc-700"
          onClick={e => e.stopPropagation()}
        >
          {props.suggestions.map((s) => (
            <InlineSuggestionRow key={s.id} s={s} onDecide={props.onDecide} busy={props.busy} />
          ))}
        </div>
      ) : null}
    </div>
  )
}

// -----------------------------------------------------------------------------
// DOCX preview (client renders the binary with mammoth)
// -----------------------------------------------------------------------------

export function DocxPreview({ sessionId }: { sessionId: string }) {
  const [html, setHtml] = useState<string>('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    async function run() {
      try {
        const res = await fetch(`${API_BASE}/api/sessions/${sessionId}/raw`)
        if (!res.ok) throw new Error(`raw fetch failed: ${res.status}`)
        const buf = await res.arrayBuffer()
        // Lazy-import mammoth so SSR doesn't try to bundle it.
        const mammoth = (await import('mammoth')).default ?? (await import('mammoth'))
        const result = await mammoth.convertToHtml({ arrayBuffer: buf })
        if (!cancelled) setHtml(result.value)
      } catch (e) {
        if (!cancelled) setError(String(e))
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    run()
    return () => {
      cancelled = true
    }
  }, [sessionId])

  if (loading) return <div className="text-sm text-zinc-500">Rendering DOCX…</div>
  if (error)
    return <div className="text-sm text-red-600">Failed to render DOCX: {error}</div>
  return (
    <div
      className="prose prose-zinc max-w-none dark:prose-invert"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}
