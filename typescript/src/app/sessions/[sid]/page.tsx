// Server wrapper for the dynamic /sessions/[sid] route. The interactive
// view is a client component (`./view`) which reads the real `sid` from the
// URL via `useParams()` at runtime. This wrapper exists so we can declare
// `generateStaticParams` -- required by `output: 'export'` -- without
// putting it inside a 'use client' file (Next.js forbids that).
//
// We pre-render a single placeholder slug "_". When FastAPI serves the
// static bundle it rewrites every /sessions/<real-sid>/ request to the
// placeholder's index.html, and the client view picks up the actual sid
// from `window.location` via Next's client router.
import SessionView from './view'

export function generateStaticParams() {
  return [{ sid: '_' }]
}

export const dynamicParams = false

export default function SessionPage() {
  return <SessionView />
}
