'use client'

/**
 * JournalPicker — native-HTML searchable journal selector.
 * Supports keyword search (name / scope / keywords), discipline tag filter,
 * and direct journal name selection.
 */

import { useEffect, useMemo, useRef, useState, useCallback } from 'react'
import { api, type SkillSummary } from '@/lib/api'

type Props = {
  value: string               // currently selected journal key
  onChange: (key: string) => void
  disabled?: boolean
  className?: string          // applied to the trigger button (e.g. width)
  placeholder?: string
}

export function JournalPicker({ value, onChange, disabled, className, placeholder }: Props) {
  const [skills, setSkills] = useState<SkillSummary[]>([])
  const [query, setQuery] = useState('')
  const [activeTags, setActiveTags] = useState<Set<string>>(new Set())
  const [open, setOpen] = useState(false)
  const [tagsExpanded, setTagsExpanded] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const TAG_LIMIT = 6

  useEffect(() => {
    api.listSkills().then((r) => setSkills(r.skills)).catch(() => {})
  }, [])

  // Close on outside click
  useEffect(() => {
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const allTags = useMemo(() => {
    const s = new Set<string>()
    for (const sk of skills) for (const d of sk.disciplines) s.add(d)
    return Array.from(s).sort()
  }, [skills])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return skills.filter((s) => {
      if (activeTags.size > 0 && !s.disciplines.some((d) => activeTags.has(d))) return false
      if (!q) return true
      return (
        s.name.toLowerCase().includes(q) ||
        s.publisher.toLowerCase().includes(q) ||
        s.scope.toLowerCase().includes(q) ||
        s.scope_keywords.some((kw) => kw.toLowerCase().includes(q)) ||
        s.disciplines.some((d) => d.toLowerCase().includes(q))
      )
    })
  }, [skills, query, activeTags])

  const selected = skills.find((s) => s.key === value)

  function pick(key: string) {
    onChange(key)
    setOpen(false)
    setQuery('')
  }

  function toggleTag(tag: string) {
    setActiveTags((prev) => {
      const next = new Set(prev)
      next.has(tag) ? next.delete(tag) : next.add(tag)
      return next
    })
  }

  const ph = placeholder ?? '— select journal —'

  return (
    <div ref={ref} className="relative">
      {/* ── Trigger: looks identical to a native <select> ── */}
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((o) => !o)}
        className={
          'flex w-full items-center justify-between gap-2 rounded border border-zinc-300 bg-white px-2.5 py-1.5 text-sm ' +
          'text-left dark:border-zinc-600 dark:bg-zinc-800 dark:text-zinc-100 ' +
          'disabled:cursor-not-allowed disabled:opacity-50 ' +
          (open ? 'ring-2 ring-blue-500 ring-offset-0 ' : '') +
          (className ?? 'w-48')
        }
      >
        <span className={`min-w-0 truncate ${selected ? '' : 'text-zinc-400'}`}>
          {selected ? selected.name : ph}
        </span>
        <svg className="size-3.5 shrink-0 text-zinc-400" viewBox="0 0 16 16" fill="currentColor">
          <path d="M4 6l4 4 4-4" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
      </button>

      {/* ── Dropdown panel ── */}
      {open && (
        <div className="absolute left-0 z-50 mt-1 min-w-[18rem] max-w-sm rounded border border-zinc-200 bg-white shadow-md dark:border-zinc-700 dark:bg-zinc-900">
          {/* Search input */}
          <div className="p-2">
            <input
              autoFocus
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search name, scope, keywords…"
              className="w-full rounded border border-zinc-300 bg-white px-2.5 py-1.5 text-sm outline-none dark:border-zinc-600 dark:bg-zinc-800"
            />
          </div>

          {/* Discipline tags — collapsed to TAG_LIMIT by default */}
          {allTags.length > 0 && (
            <div className="border-t border-zinc-100 px-2 pb-2 pt-1.5 dark:border-zinc-700">
              <div className="flex flex-wrap gap-1">
                {(tagsExpanded ? allTags : allTags.slice(0, TAG_LIMIT)).map((tag) => (
                  <button
                    key={tag}
                    type="button"
                    onClick={() => toggleTag(tag)}
                    className={`rounded-full border px-2 py-0.5 text-xs transition ${
                      activeTags.has(tag)
                        ? 'border-blue-500 bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300'
                        : 'border-zinc-200 bg-white text-zinc-500 hover:border-zinc-300 hover:text-zinc-700 dark:border-zinc-600 dark:bg-zinc-800 dark:text-zinc-400'
                    }`}
                  >
                    {tag.replace(/_/g, ' ')}
                  </button>
                ))}
                {allTags.length > TAG_LIMIT && (
                  <button type="button" onClick={() => setTagsExpanded(v => !v)}
                    className="rounded-full border border-dashed border-zinc-300 px-2 py-0.5 text-xs text-zinc-400 hover:text-zinc-600 dark:border-zinc-600">
                    {tagsExpanded ? '▲ less' : `+${allTags.length - TAG_LIMIT} more`}
                  </button>
                )}
                {activeTags.size > 0 && (
                  <button type="button" onClick={() => setActiveTags(new Set())}
                    className="text-xs text-blue-500 hover:underline ml-1">
                    clear
                  </button>
                )}
              </div>
            </div>
          )}

          {/* Results list */}
          <div className="max-h-60 overflow-y-auto border-t border-zinc-100 dark:border-zinc-700">
            {filtered.length === 0 ? (
              <p className="px-3 py-2 text-xs text-zinc-400">No journals match.</p>
            ) : (
              filtered.map((s) => (
                <button
                  key={s.key}
                  type="button"
                  onClick={() => pick(s.key)}
                  className={`flex w-full flex-col items-start px-3 py-2 text-left text-sm transition hover:bg-zinc-50 dark:hover:bg-zinc-800 ${
                    s.key === value ? 'bg-blue-50 dark:bg-blue-900/20' : ''
                  }`}
                >
                  <div className="flex w-full items-center justify-between gap-2">
                    <span className="font-medium">{s.name}</span>
                    {s.impact_factor != null && (
                      <span className="shrink-0 text-xs text-zinc-400">IF {s.impact_factor}</span>
                    )}
                  </div>
                  <span className="text-xs text-zinc-400">{s.publisher}</span>
                  <div className="mt-0.5 flex flex-wrap gap-0.5">
                    {s.disciplines.slice(0, 4).map((d) => (
                      <span key={d} className="rounded border border-zinc-200 bg-zinc-50 px-1.5 py-px text-[10px] text-zinc-500 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-400">
                        {d.replace(/_/g, ' ')}
                      </span>
                    ))}
                  </div>
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  )
}
