'use client'

import { Heading } from '@/components/heading'
import { Button } from '@/components/button'
import { Badge } from '@/components/badge'
import { useEffect, useRef, useState } from 'react'
import { useSSE } from '@/lib/sse'
import { api } from '@/lib/api'
import { useI18n } from '@/lib/i18n'

export default function LogsPage() {
  const { t } = useI18n()
  const [streaming, setStreaming] = useState(true)
  const liveMsgs = useSSE(streaming ? api.logsStreamUrl() : null, 500)
  const [history, setHistory] = useState<string[]>([])
  const [loadingHistory, setLoadingHistory] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  async function loadHistory() {
    setLoadingHistory(true)
    try {
      const r = await api.logHistory(2000)
      setHistory(r.lines)
    } catch {
      // ignore; show whatever we have
    } finally {
      setLoadingHistory(false)
    }
  }

  useEffect(() => { loadHistory() }, [])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [liveMsgs.length])

  const totalLines = history.length + liveMsgs.filter(m => m.event !== 'ping').length

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <Heading>{t('logs.title')}</Heading>
        <div className="flex items-center gap-2">
          <Badge color={streaming ? 'emerald' : 'zinc'}>
            {streaming ? '● live' : '⏸ paused'}
          </Badge>
          <span className="text-xs text-zinc-500">{totalLines} {t('logs.lines')}</span>
          <Button outline onClick={() => setStreaming((v) => !v)}>
            {streaming ? t('logs.pause') : t('logs.resume')}
          </Button>
          <Button outline onClick={loadHistory} disabled={loadingHistory}>
            {loadingHistory ? t('common.loading') : t('logs.refresh_history')}
          </Button>
        </div>
      </div>

      <div className="rounded-xl border border-zinc-950/10 bg-zinc-950 p-4 font-mono text-xs dark:border-white/10">
        <pre className="max-h-[76vh] overflow-auto whitespace-pre-wrap">
          {/* historical lines — dimmer */}
          {history.length === 0 && loadingHistory && (
            <span className="text-zinc-600">{t('common.loading')}</span>
          )}
          {history.map((line, i) => (
            <div key={`h-${i}`} className="text-zinc-400">{line}</div>
          ))}
          {/* separator between history and live */}
          {history.length > 0 && (
            <div className="my-1 border-t border-zinc-700 text-zinc-600">
              ── live ──
            </div>
          )}
          {/* live lines — brighter */}
          {liveMsgs.length === 0 && !loadingHistory && (
            <span className="text-zinc-600">Waiting for live log lines…</span>
          )}
          {liveMsgs.map((m, i) => (
            <div key={`l-${i}`} className={m.event === 'ping' ? 'text-zinc-700' : 'text-emerald-300'}>
              {m.event !== 'ping' && `[${m.event}] `}{m.data}
            </div>
          ))}
          <div ref={bottomRef} />
        </pre>
      </div>
    </div>
  )
}
