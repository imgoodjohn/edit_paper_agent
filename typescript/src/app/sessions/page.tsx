'use client'

import { Badge } from '@/components/badge'
import { Button } from '@/components/button'
import { Heading, Subheading } from '@/components/heading'
import { Link } from '@/components/link'
import { Text } from '@/components/text'
import { useEffect, useState } from 'react'
import { api, type SessionSummary, type SkillSummary } from '@/lib/api'
import { useI18n } from '@/lib/i18n'

function fmtDate(ts: number) {
  if (!ts) return '—'
  return new Date(ts * 1000).toLocaleString()
}

export default function SessionsIndex() {
  const { t } = useI18n()
  const [sessions, setSessions] = useState<SessionSummary[]>([])
  const [skills, setSkills] = useState<SkillSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const r = await api.listSessions()
      setSessions(r.sessions)
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    api.listSkills().then(r => setSkills(r.skills)).catch(() => {})
  }, [])

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <Heading>Sessions</Heading>
        <Button outline onClick={load} disabled={loading}>
          {loading ? t('common.loading') : t('logs.refresh_history')}
        </Button>
      </div>

      {error && <Text className="text-red-500">{error}</Text>}

      {!loading && sessions.length === 0 && !error && (
        <Text className="text-zinc-500">
          No sessions yet. <Link href="/">Upload a manuscript</Link> to get started.
        </Text>
      )}

      <div className="space-y-3">
        {sessions.map((s) => (
          <Link
            key={s.id}
            href={`/sessions/${s.id}/`}
            className="block rounded-xl border border-zinc-200 bg-white px-5 py-4 shadow-sm transition hover:border-zinc-400 hover:shadow-md dark:border-zinc-700 dark:bg-zinc-900 dark:hover:border-zinc-500"
          >
            <div className="flex items-center justify-between gap-4">
              <div className="space-y-1 min-w-0">
                <div className="flex items-center gap-2">
                  <Subheading className="truncate font-mono text-sm">{s.id}</Subheading>
                  <Badge color={s.source_type === 'latex' ? 'blue' : 'purple'}>
                    {s.source_type === 'latex' ? 'LaTeX' : 'Word'}
                  </Badge>
                  {s.journal_key && (
                    <Badge color="zinc">
                      {skills.find(sk => sk.key === s.journal_key)?.name ?? s.journal_key.replace(/_/g, ' ')}
                    </Badge>
                  )}
                  {s.plan_approved && <Badge color="emerald">Plan Approved</Badge>}
                </div>
                <Text className="text-xs text-zinc-500">{fmtDate(s.created_at)}</Text>
              </div>
              <div className="flex shrink-0 items-center gap-3 text-xs text-zinc-500">
                {s.n_suggestions > 0 && (
                  <>
                    <span className="text-emerald-600 dark:text-emerald-400">
                      ✓ {s.n_accepted}
                    </span>
                    <span className="text-amber-600 dark:text-amber-400">
                      ● {s.n_pending} pending
                    </span>
                    <span className="text-zinc-400">/ {s.n_suggestions} total</span>
                  </>
                )}
              </div>
            </div>
          </Link>
        ))}
      </div>
    </div>
  )
}
