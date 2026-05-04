'use client'

import { useEffect, useState } from 'react'
import { api, type DocStructure } from '@/lib/api'
import { useI18n } from '@/lib/i18n'
import { Badge } from '@/components/badge'
import { Button } from '@/components/button'

type Props = {
  sid: string
  onConfirm: () => void
  busy: boolean
}

function structureIssues(s: DocStructure, t: (k: string) => string): string[] {
  const issues: string[] = []
  if (!s.has_abstract) issues.push(t('structure.warn_no_abstract'))
  if (s.sections.length === 0) issues.push(t('structure.warn_no_sections'))
  if (s.stats.words < 500) issues.push(`${t('structure.warn_few_words')} (${s.stats.words})`)
  return issues
}

export function DocStructurePreview({ sid, onConfirm, busy }: Props) {
  const { t } = useI18n()
  const [structure, setStructure] = useState<DocStructure | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.getStructure(sid)
      .then(setStructure)
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [sid])

  if (loading) return <p className="text-sm text-zinc-400">{t('common.loading')}</p>
  if (!structure) return null

  const issues = structureIssues(structure, t)
  const emptyCount = structure.sections.filter((s) => s.n_words === 0).length

  return (
    <div className="space-y-3 rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-700 dark:bg-zinc-900">
      {/* Summary chips */}
      <div className="flex flex-wrap gap-2">
        <Badge color="zinc">{t('structure.title')}: {structure.title || '—'}</Badge>
        <Badge color={structure.has_abstract ? 'zinc' : 'amber'}>
          {structure.has_abstract
            ? `${t('structure.abstract')}: ${structure.abstract_words} ${t('structure.words')}`
            : t('structure.abstract_missing')}
        </Badge>
        <Badge color="zinc">{structure.stats.words} {t('structure.words')}</Badge>
        <Badge color={structure.n_references === 0 ? 'amber' : 'zinc'}>
          {structure.n_references} {t('structure.refs')}
        </Badge>
        {emptyCount > 0 && (
          <Badge color="amber">⚠ {emptyCount} {t('structure.empty_sections')}</Badge>
        )}
      </div>

      {/* Parse warnings */}
      {issues.length > 0 && (
        <ul className="rounded border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-600/40 dark:bg-amber-900/20 dark:text-amber-300">
          {issues.map((w, i) => <li key={i}>⚠ {w}</li>)}
        </ul>
      )}

      {/* Section tree */}
      {structure.sections.length === 0 ? (
        <p className="text-xs text-amber-600">{t('structure.no_sections')}</p>
      ) : (
        <details open>
          <summary className="cursor-pointer select-none text-xs font-medium text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300">
            {structure.sections.length} {t('structure.sections')}
          </summary>
          <ul className="mt-2 space-y-0.5">
            {structure.sections.map((s) => {
              const empty = s.n_words === 0
              return (
                <li
                  key={s.id}
                  className="flex items-baseline gap-2 text-xs"
                  style={{ paddingLeft: `${(s.level - 1) * 16}px` }}
                >
                  <span className="shrink-0 text-zinc-400">{'·'.repeat(s.level)}</span>
                  <span className={`font-medium ${empty ? 'text-amber-600 dark:text-amber-400' : ''}`}>
                    {s.title || '(untitled)'}
                  </span>
                  <span className={empty ? 'text-amber-500 dark:text-amber-400' : 'text-zinc-400'}>
                    {s.n_words} {t('structure.words')} · {s.n_paras} {t('structure.paras')}
                    {empty ? ' ⚠' : ''}
                  </span>
                </li>
              )
            })}
          </ul>
        </details>
      )}

      <div className="flex justify-end pt-1">
        <Button color="emerald" onClick={onConfirm} disabled={busy}>
          {busy ? t('common.running') : t('session.structure_confirm')}
        </Button>
      </div>
    </div>
  )
}
