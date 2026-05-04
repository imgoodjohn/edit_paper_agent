// Tiny SSE hook. Subscribes to an EventSource and pushes incoming events
// into local state. Use for log streaming or per-session progress.
'use client'

import { useEffect, useState } from 'react'

export type SSEMessage = {
  event: string
  data: string
  ts: number
}

export function useSSE(url: string | null, max = 200): SSEMessage[] {
  const [msgs, setMsgs] = useState<SSEMessage[]>([])
  useEffect(() => {
    if (!url) return
    const es = new EventSource(url)
    const push = (event: string) => (e: MessageEvent) => {
      setMsgs((prev) => {
        const next = [...prev, { event, data: e.data ?? '', ts: Date.now() }]
        if (next.length > max) next.splice(0, next.length - max)
        return next
      })
    }
    es.addEventListener('message', push('message') as EventListener)
    es.addEventListener('log', push('log') as EventListener)
    es.addEventListener('progress', push('progress') as EventListener)
    es.addEventListener('ready', push('ready') as EventListener)
    es.addEventListener('ping', push('ping') as EventListener)
    es.onerror = () => {
      // EventSource auto-reconnects; nothing to do.
    }
    return () => es.close()
  }, [url, max])
  return msgs
}
