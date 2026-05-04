'use client'

import { Alert, AlertActions, AlertBody, AlertTitle } from '@/components/alert'
import { Badge } from '@/components/badge'
import { Button } from '@/components/button'
import { Divider } from '@/components/divider'
import { Heading, Subheading } from '@/components/heading'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/table'
import { Text, Strong } from '@/components/text'
import { Textarea } from '@/components/textarea'
import React, { useEffect, useMemo, useRef, useState, useCallback } from 'react'
import { useParams } from 'next/navigation'
import {
  api,
  type AIDetectionResult,
  type ComprehensionCard,
  type JournalRanking,
  type Plan,
  type ReviewReport,
  type SessionDoc,
  type SkillSummary,
  type Suggestion,
  type TodoItem,
} from '@/lib/api'
import { useSSE, type SSEMessage } from '@/lib/sse'
import { LatexPreview, DocxPreview, type PreviewBlock } from '@/lib/preview'
import { useI18n } from '@/lib/i18n'
import { Wizard, type WizardStep } from '@/components/wizard'
import { ModelPicker } from '@/components/model-picker'
import { ToolCallsView, type ToolCall } from '@/components/tool-calls'
import { JournalPicker } from '@/components/journal-picker'
import { DocStructurePreview } from '@/components/doc-structure-preview'
import { Listbox, ListboxOption, ListboxLabel } from '@/components/listbox'
import { Checkbox } from '@/components/checkbox'

const sevColor: Record<string, 'red' | 'amber' | 'zinc'> = {
  critical: 'red',
  warning: 'amber',
  info: 'zinc',
}

/** Convert snake_case / space-separated string to PascalCase (no spaces). */
function toPascal(s: string): string {
  return s
    .replace(/[_\s]+/g, ' ')
    .trim()
    .split(' ')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join('')
}

/** Convert snake_case / space-separated string to Title Case (with spaces). */
function toTitle(s: string): string {
  return s
    .replace(/[_\s]+/g, ' ')
    .trim()
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

function StatusBadge({ status }: { status: string }) {
  const { t } = useI18n()
  if (status === 'accepted') return <Badge color="emerald">{t('common.accepted')}</Badge>
  if (status === 'rejected') return <Badge color="red">{t('common.rejected')}</Badge>
  if (status === 'modified') return <Badge color="blue">{t('common.modified')}</Badge>
  return <Badge color="zinc">{t('common.pending')}</Badge>
}

export default function SessionView() {
  const params = useParams<{ sid: string }>()
  // In `output: 'export'` mode Next.js pre-renders a single `_` placeholder.
  // FastAPI serves that HTML for every /sessions/<real-sid>/ URL, so
  // useParams() returns '_'. Read the real ID from the browser URL instead.
  const sid = useMemo(() => {
    const p = params.sid
    if (p && p !== '_') return p
    if (typeof window !== 'undefined') {
      const m = window.location.pathname.match(/\/sessions\/([^/]+)/)
      if (m && m[1] !== '_') return m[1]
    }
    return p
  }, [params.sid])

  const [session, setSession] = useState<SessionDoc | null>(null)
  const [skills, setSkills] = useState<SkillSummary[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [language, setLanguage] = useState<'en' | 'zh'>('en')
  const [useTools, setUseTools] = useState(true)
  // Per-section model overrides (empty = use server tier default)
  const [analysisModel, setAnalysisModel] = useState<string>('')  // comprehend + plan
  const [editModel, setEditModel] = useState<string>('')           // run editors
  const [reportModel, setReportModel] = useState<string>('')       // report + AI detect
  // tool_log grouped by todo_id — seeded from session, then appended via SSE
  const [toolCalls, setToolCalls] = useState<Record<string, ToolCall[]>>({})

  const [ranking, setRanking] = useState<JournalRanking | null>(null)
  const [report, setReport] = useState<ReviewReport | null>(null)
  const [aiDet, setAiDet] = useState<AIDetectionResult | null>(null)
  const [exportSummary, setExportSummary] = useState<{
    accepted: number; modified: number; pending: number; rejected: number;
    skipped_not_found: number; flagged_pending: string[]; written_path: string;
    download_url: string
  } | null>(null)
  const [pageWarnings, setPageWarnings] = useState<string[]>([])
  const [author, setAuthor] = useState('Paper-Agent AI')
  const [corrections, setCorrections] = useState('')
  const [previewOpen, setPreviewOpen] = useState(false)
  const [focusedPid, setFocusedPid] = useState<string | null>(null)
  const [preview, setPreview] = useState<{
    title: string
    source_type: 'latex' | 'docx'
    blocks: PreviewBlock[]
  } | null>(null)
  const [structureStats, setStructureStats] = useState<{
    abstract_words: number
    total_words: number
    n_references: number
  } | null>(null)

  const refresh = useCallback(async () => {
    try {
      const s = await api.getSession(sid)
      setSession(s)
      setCorrections(s.user_corrections ?? '')
    } catch (e) {
      setError(String(e))
    }
  }, [sid])

  useEffect(() => {
    refresh()
    api.listSkills().then((r) => setSkills(r.skills)).catch(() => {})
    api.getPreview(sid)
      .then((r) => setPreview({ title: r.title, source_type: r.source_type, blocks: r.blocks }))
      .catch(() => {})
    api.getStructure(sid)
      .then((r) => setStructureStats({ abstract_words: r.abstract_words ?? 0, total_words: r.stats?.words ?? 0, n_references: r.n_references ?? 0 }))
      .catch(() => {})
    // seed persisted report, ai_detection, and tool_log from session
    api.getSession(sid).then((s) => {
      if (s.review_report) setReport(s.review_report)
      if (s.ai_detection) setAiDet(s.ai_detection)
      const grouped: Record<string, ToolCall[]> = {}
      for (const tc of (s as any).tool_log ?? []) {
        if (!grouped[tc.todo_id]) grouped[tc.todo_id] = []
        grouped[tc.todo_id].push(tc)
      }
      setToolCalls(grouped)
    }).catch(() => {})
  }, [refresh, sid])

  const progress = useSSE(sid ? api.progressStreamUrl(sid) : null, 200)

  // Derive per-TODO progress from SSE events (most-recent wins).
  const todoProgress = useMemo(() => {
    const out: Record<
      string,
      { paragraphs_done: number; batch_idx: number; batch_total: number; new: number }
    > = {}
    for (const m of progress) {
      if (m.event !== 'progress') continue
      try {
        const p = JSON.parse(m.data)
        if (p.kind === 'edit_batch' && p.todo_id) {
          const prev = out[p.todo_id]
          out[p.todo_id] = {
            paragraphs_done: p.paragraphs_done ?? 0,
            batch_idx: p.batch_idx ?? 0,
            batch_total: p.batch_total ?? 1,
            new: (prev?.new ?? 0) + (p.new_suggestions ?? 0),
          }
        }
      } catch {}
    }
    return out
  }, [progress])

  // Accumulate live tool_call SSE events
  useEffect(() => {
    for (const m of progress) {
      if (m.event !== 'progress') continue
      try {
        const p = JSON.parse(m.data)
        if (p.kind === 'tool_call' && p.todo_id) {
          setToolCalls((prev) => {
            const existing = prev[p.todo_id] ?? []
            const tc: ToolCall = {
              id: `live-${Date.now()}-${Math.random()}`,
              tool: p.tool,
              args: p.args ?? {},
              summary: p.summary ?? '',
              result: p.result ?? {},
              error: p.error ?? null,
              ts: p.ts,
            }
            return { ...prev, [p.todo_id]: [...existing, tc] }
          })
        }
      } catch {}
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [progress.length])

  // Currently-running stage banner
  const currentStage = useMemo(() => {
    let s: { stage: string; todo_title?: string } | null = null
    for (const m of progress) {
      if (m.event !== 'progress') continue
      try {
        const p = JSON.parse(m.data)
        if (p.kind === 'stage_started') s = { stage: p.stage, todo_title: p.todo_title }
        else if (p.kind === 'stage_done') s = null
      } catch {}
    }
    return s
  }, [progress])

  const wrap = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(label)
    setError(null)
    try {
      await fn()
      await refresh()
    } catch (e) {
      setError(String(e))
    } finally {
      setBusy(null)
    }
  }

  // Pull i18n out so subcomponents and the wizard share the same dictionary.
  const { t } = useI18n()

  if (!session) {
    return (
      <div className="space-y-4">
        <Heading>{t('common.loading')}</Heading>
        {error ? <Text className="text-red-600">{error}</Text> : null}
      </div>
    )
  }

  // ----- Wizard step state derived purely from the session record -----
  // Step 1 done when the user has confirmed the comprehension.
  // Step 2 done when the plan is approved.
  // Step 3 done when at least one TODO has actually been editor-run
  //   (any suggestion exists for it).
  // Step 4 done when both review report and AI detection have run.
  // Step 5 done when the user has triggered an export (we use
  //   `exportSummary` -- session-local; resets on reload, which is fine).
  const todoIdsWithSugg = new Set(
    Object.values(session.suggestions ?? {}).map((s: Suggestion) => s.todo_id),
  )
  const step3Done =
    !!session.plan && session.plan.todos.some((td) => todoIdsWithSugg.has(td.id))
  const wizardSteps: WizardStep[] = [
    { id: 1, label: t('wizard.s1'), done: session.comprehension_confirmed },
    { id: 2, label: t('wizard.s2'), done: session.plan_approved },
    { id: 3, label: t('wizard.s3'), done: step3Done },
    { id: 4, label: t('wizard.s4'), done: !!report && !!aiDet },
    { id: 5, label: t('wizard.s5'), done: !!exportSummary },
  ]
  const wizardCurrent =
    !session.comprehension_confirmed ? 1 :
    !session.plan_approved ? 2 :
    !step3Done ? 3 :
    !(report && aiDet) ? 4 : 5

  const suggestions = Object.values(session.suggestions ?? {}) as Suggestion[]
  const pending = suggestions.filter((s: Suggestion) => s.status === 'pending')
  const flaggedPending = pending.filter((s: Suggestion) => s.flag_for_user)

  return (
    <div className="space-y-10">
      {/* ============ HEADER ============ */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <Heading>{session.id}</Heading>
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-sm">
            {session.source_type === 'latex'
              ? <span className="rounded bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300">{t('session.source_latex')}</span>
              : <span className="rounded bg-blue-100 px-2 py-0.5 text-xs font-semibold text-blue-800 dark:bg-blue-900/30 dark:text-blue-300">{t('session.source_word')}</span>
            }
            <span className="text-zinc-400">&middot;</span>
            {session.journal_key ? (() => {
              const sk = skills.find(s => s.key === session.journal_key)
              const at = sk?.article_types?.[0]
              const hasLimits = !!(at?.abstract_limit || at?.word_limit || at?.pages_max || at?.references_max)
              const abstractOver = at?.abstract_limit && structureStats ? structureStats.abstract_words > at.abstract_limit : false
              const wordOver = at?.word_limit && structureStats ? structureStats.total_words > at.word_limit : false
              const refOver = at?.references_max && structureStats ? structureStats.n_references > at.references_max : false
              return (
                <>
                  <Badge color="blue">{sk?.name ?? session.journal_key}</Badge>
                  {at?.pages_max ? <span className="text-xs text-zinc-500">{at.pages_max} {t('session.pages_max')}</span> : null}
                  {at?.abstract_limit && structureStats ? (
                    <span className={`text-xs ${abstractOver ? 'text-red-500 font-semibold' : 'text-zinc-500'}`}>
                      {t('session.abstract_limit')} {structureStats.abstract_words}/{at.abstract_limit}w{abstractOver ? ' ⚠️' : ''}
                    </span>
                  ) : null}
                  {at?.word_limit && structureStats ? (
                    <span className={`text-xs ${wordOver ? 'text-red-500 font-semibold' : 'text-zinc-500'}`}>
                      {structureStats.total_words}/{at.word_limit} {t('session.word_limit')}{wordOver ? ' ⚠️' : ''}
                    </span>
                  ) : null}
                  {at?.references_max && structureStats ? (
                    <span className={`text-xs ${refOver ? 'text-red-500 font-semibold' : 'text-zinc-500'}`}>
                      {structureStats.n_references}/{at.references_max} refs{refOver ? ' ⚠️' : ''}
                    </span>
                  ) : null}
                  {!hasLimits && structureStats ? (
                    <span className="text-xs text-amber-600 dark:text-amber-400" title={t('session.no_limits_hint')}>
                      {structureStats.total_words}w · {t('session.no_limits')}
                    </span>
                  ) : null}
                </>
              )
            })() : <Badge color="amber">{t('session.not_set')}</Badge>}
          </div>
        </div>
        <div className="flex items-center gap-3">
          <label className="text-xs text-zinc-500 whitespace-nowrap">{t('session.lang_label')}:</label>
          <Listbox<string>
            value={language}
            onChange={(v) => setLanguage(v as 'en' | 'zh')}
            className="w-28"
          >
            <ListboxOption value="en"><ListboxLabel>English</ListboxLabel></ListboxOption>
            <ListboxOption value="zh"><ListboxLabel>中文</ListboxLabel></ListboxOption>
          </Listbox>
        </div>
      </div>

      {/* ============ WIZARD / STEPPER ============ */}
      <Wizard steps={wizardSteps} current={wizardCurrent} />

      {/* ============ CURRENT-STAGE BANNER ============ */}
      {currentStage ? (
        <div className="flex items-center gap-3 rounded-lg border border-blue-300 bg-blue-50 p-3 text-sm dark:border-blue-500/30 dark:bg-blue-500/10">
          <div className="size-2 rounded-full bg-blue-500" />
          <Strong>{t('ai.working')}:</Strong>
          <span>{currentStage.stage}</span>
          {currentStage.todo_title ? (
            <span className="text-zinc-500">— {currentStage.todo_title}</span>
          ) : null}
        </div>
      ) : null}

      {/* ============ JOURNAL PICKER (when not set) ============ */}
      {!session.journal_key ? (
        <section className="space-y-3 rounded-xl border border-amber-300 bg-amber-50 p-4 dark:border-amber-500/30 dark:bg-amber-500/10">
          <Subheading>{t('session.no_journal')}</Subheading>
          <Text>{t('session.no_journal_hint')}</Text>
          <div className="flex flex-wrap items-center gap-3">
            <JournalPicker
              value={session.journal_key ?? ''}
              onChange={(v) => { if (v) wrap('set-journal', () => api.setJournal(sid, v)) }}
              disabled={!!busy}
              className="w-64"
            />
            <Button
              onClick={() =>
                wrap('predict-journal', async () => {
                  const r = await api.predictJournal(sid)
                  setRanking(r)
                })
              }
              disabled={!!busy}
            >
              {busy === 'predict-journal' ? t('common.running') : t('session.auto_pick')}
            </Button>
          </div>

          {ranking ? (
            <div className="mt-4 space-y-2">
              <Subheading>{t('session.ranking')}</Subheading>
              <Text>{ranking.rationale}</Text>
              <Table dense>
                <TableHead>
                  <TableRow>
                    <TableHeader>{t('session.rank_journal')}</TableHeader>
                    <TableHeader>{t('session.rank_score')}</TableHeader>
                    <TableHeader>{t('session.rank_article_type')}</TableHeader>
                    <TableHeader>{t('session.rank_reasons')}</TableHeader>
                    <TableHeader>{t('session.rank_concerns')}</TableHeader>
                    <TableHeader>{t('session.rank_pick')}</TableHeader>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {ranking.ranked.map((r) => (
                    <TableRow key={r.journal_key}>
                      <TableCell><Strong>{r.journal_name}</Strong></TableCell>
                      <TableCell>{r.score}</TableCell>
                      <TableCell>{r.recommended_article_type || '—'}</TableCell>
                      <TableCell>{r.fit_reasons.join('; ')}</TableCell>
                      <TableCell>{r.concerns.join('; ')}</TableCell>
                      <TableCell>
                        <Button
                          onClick={() =>
                            wrap('set-journal', () => api.setJournal(sid, r.journal_key))
                          }
                          disabled={!!busy}
                        >
                          {t('session.use')}
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : null}
        </section>
      ) : null}

      {/* ============ DOCUMENT PREVIEW (inline review) ============ */}
      {preview ? (
        <section className="space-y-2">
          <div className="flex items-center gap-3">
            <Subheading>{t('session.preview')}</Subheading>
            <button
              type="button"
              onClick={() => setPreviewOpen(v => !v)}
              className="rounded border border-zinc-300 px-2.5 py-0.5 text-xs text-zinc-500 hover:border-zinc-400 hover:text-zinc-700 dark:border-zinc-600 dark:hover:border-zinc-500"
            >
              {previewOpen ? t('session.preview_hide') : t('session.preview_show')}
            </button>
            {focusedPid && (
              <button
                type="button"
                onClick={() => setFocusedPid(null)}
                className="rounded border border-zinc-300 px-2.5 py-0.5 text-xs text-zinc-500 hover:border-zinc-400 dark:border-zinc-600"
              >
                ✕ {t('session.preview_close_suggestion')}
              </button>
            )}
          </div>
          {previewOpen && (
            <div className="max-h-[70vh] overflow-auto rounded-lg border border-zinc-200 bg-white p-5 dark:border-zinc-700 dark:bg-zinc-900">
              {preview.source_type === 'latex' ? (
                <LatexPreview
                  blocks={preview.blocks}
                  suggestionsByParagraph={(() => {
                    const out: Record<string, Suggestion[]> = {}
                    for (const s of suggestions) {
                      if (!out[s.paragraph_id]) out[s.paragraph_id] = []
                      out[s.paragraph_id].push(s)
                    }
                    return out
                  })()}
                  focusedPid={focusedPid}
                  onParagraphClick={(pid) => setFocusedPid(p => p === pid ? null : pid)}
                  onDecide={async (id, d, after) => {
                    await wrap('decide', () => api.decide(sid, id, d, after))
                  }}
                  busy={busy}
                />
              ) : (
                <DocxPreview sessionId={sid} />
              )}
            </div>
          )}
        </section>
      ) : null}

      {/* ============ COMPREHENSION ============ */}
      <section className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Subheading>{t('session.understanding')}</Subheading>
          <div className="flex flex-wrap items-center gap-2">
            <ModelPicker value={analysisModel} onChange={setAnalysisModel} label={t('model.analysis')} width="min-w-[200px]" />
            <Button
              onClick={() =>
                wrap('comprehend', async () => {
                  await api.comprehend(sid, {
                    ...(analysisModel ? { model: analysisModel } : {}),
                  })
                })
              }
              disabled={!!busy}
            >
              {session.comprehension
                ? t('session.regenerate')
                : t('session.generate_understanding')}
            </Button>
          </div>
        </div>

        {session.comprehension ? (
          <ComprehensionView
            card={session.comprehension}
            confirmed={session.comprehension_confirmed}
            corrections={corrections}
            onCorrectionsChange={setCorrections}
            onConfirm={() =>
              wrap('confirm-comp', async () => {
                await api.confirmComprehension(sid, corrections)
              })
            }
            busy={busy}
          />
        ) : (
          <Text>{t('session.start_comprehension_hint')}</Text>
        )}
      </section>

      {session.comprehension ? <Divider /> : null}

      {/* ============ PLAN ============ */}
      <section className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Subheading>{t('session.plan')}</Subheading>
          <div className="flex flex-wrap items-center gap-2">
            {!session.plan ? (
              <span className="text-xs text-zinc-400">{t('model.analysis')} ↑</span>
            ) : null}
            {session.plan ? (
              <>
                <Button
                  onClick={() =>
                    wrap('plan', () => api.makePlan(sid, { ...(analysisModel ? { model: analysisModel } : {}) }))
                  }
                  disabled={!!busy}
                >
                  {t('session.replan')}
                </Button>
                {!session.plan_approved ? (
                  <Button color="emerald" onClick={() => wrap('approve', () => api.approvePlan(sid))} disabled={!!busy}>
                    {t('session.approve_plan')}
                  </Button>
                ) : null}
              </>
            ) : null}
          </div>
        </div>

        {session.plan ? (
          <>
            <PlanView plan={session.plan} approved={session.plan_approved} />
            <TodoTable
              todos={session.plan.todos}
              busy={busy}
              progress={todoProgress}
              approved={session.plan_approved}
              onRun={(todo) =>
                wrap(`edit-${todo.id}`, () =>
                  api.runEditor(sid, todo.id, {
                    language,
                    use_tools: useTools,
                    ...(editModel ? { model: editModel } : {}),
                  }),
                )
              }
            />
          </>
        ) : session.comprehension_confirmed && session.journal_key ? (
          <div className="space-y-3">
            <p className="text-sm font-medium">{t('session.doc_structure')}</p>
            <DocStructurePreview
              sid={sid}
              busy={busy === 'plan'}
              onConfirm={() =>
                wrap('plan', () => api.makePlan(sid, { ...(analysisModel ? { model: analysisModel } : {}) }))
              }
            />
          </div>
        ) : (
          <Text>{t('session.confirm_before_plan_hint')}</Text>
        )}
      </section>

      {session.plan ? <Divider /> : null}

      {/* ============ EDITOR (per TODO) ============ */}
      {session.plan && session.plan_approved ? (
        <section className="space-y-4">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <Subheading>{t('session.run_editors')}</Subheading>
            <div className="flex flex-wrap items-center gap-2">
              <ModelPicker value={editModel} onChange={setEditModel} label={t('model.edit')} width="min-w-[200px]" />
              <label className="flex cursor-pointer items-center gap-2 text-xs select-none">
                <Checkbox
                  checked={useTools}
                  onChange={setUseTools}
                />
                <span className="text-zinc-600 dark:text-zinc-400">{t('session.use_tools')}</span>
              </label>
              <Button
                onClick={() =>
                  wrap('auto-grammar', () => api.autoGrammar(sid, { language, ...(editModel ? { model: editModel } : {}) }))
                }
                disabled={!!busy}
              >
                {t('session.auto_grammar')}
              </Button>
            </div>
          </div>


          {/* Tool call log per todo */}
          {session.plan.todos.map((todo) =>
            (toolCalls[todo.id]?.length ?? 0) > 0 ? (
              <div key={todo.id}>
                <p className="mb-1 text-xs font-medium text-zinc-500">{todo.title}</p>
                <ToolCallsView calls={toolCalls[todo.id]} />
              </div>
            ) : null
          )}

          <SuggestionsView
            suggestions={suggestions}
            onDecide={(id, decision, modified_after) =>
              wrap(`decide-${id}`, () => api.decide(sid, id, decision, modified_after))
            }
            busy={busy}
          />
        </section>
      ) : null}


      {/* ============ EXPORT — only after plan approved ============ */}
      {session.plan_approved ? <Divider /> : null}
      {session.plan_approved ? (
      <section className="space-y-4">
        <Subheading>{t('session.export')}</Subheading>
        <Text className="text-xs text-zinc-500">
          {t('suggestion.ai_opinion_note')}
        </Text>
        {pending.length > 0 ? (
          <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm dark:border-amber-500/30 dark:bg-amber-500/10">
            <Strong>{t('session.heads_up')}:</Strong> {pending.length} {session.source_type === 'latex' ? t('session.pending_latex_note') : t('session.pending_docx_note')}
            {flaggedPending.length > 0 ? (
              <div className="mt-1">
                {t('session.pending_flag_note').replace('{n}', String(flaggedPending.length))}
              </div>
            ) : null}
          </div>
        ) : null}

        <div className="flex flex-wrap items-end gap-3">
          {session.source_type === 'docx' ? (
            <div>
              <label className="mb-1 block text-xs font-medium text-zinc-600 dark:text-zinc-400">{t('session.author')}</label>
              <input
                type="text"
                value={author}
                onChange={(e) => setAuthor(e.target.value)}
                className="rounded border border-zinc-300 bg-white px-2.5 py-1.5 text-sm dark:border-zinc-600 dark:bg-zinc-800"
              />
            </div>
          ) : null}
          <Button
            onClick={() =>
              wrap('export', async () => {
                const r = await api.exportFile(
                  sid,
                  session.source_type === 'latex' ? 'latex' : 'docx',
                  author,
                )
                setExportSummary({ ...r.summary, download_url: r.download_url })
                setPageWarnings(r.page_warnings ?? [])
              })
            }
            disabled={!!busy}
          >
            {t('session.export_btn')} {session.source_type === 'latex' ? '.tex' : '.docx'}
          </Button>
          {exportSummary ? (
            <a
              className="text-sm font-medium text-blue-600 hover:underline"
              href={api.downloadUrl(sid, session.source_type === 'latex' ? 'latex' : 'docx')}
              download
            >
              {t('session.download')}
            </a>
          ) : null}
        </div>
        {exportSummary ? (
          <Text className="text-xs">
            Accepted: {exportSummary.accepted} · Modified: {exportSummary.modified} ·{' '}
            Pending: {exportSummary.pending} · Rejected: {exportSummary.rejected} ·{' '}
            Skipped (not found): {exportSummary.skipped_not_found}
          </Text>
        ) : null}
        {pageWarnings.length > 0 && (
          <div className="mt-2 space-y-1 rounded border border-amber-300 bg-amber-50 p-3 text-xs text-amber-800 dark:border-amber-600/40 dark:bg-amber-900/20 dark:text-amber-300">
            {pageWarnings.map((w, i) => <p key={i}>⚠ {w}</p>)}
          </div>
        )}
      </section>
      ) : null}

      <Divider />

      {/* ============ ACTIVITY — progress + decision log + report/AI ============ */}
      <section className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Subheading>{t('session.activity')}</Subheading>
          {session.plan_approved ? (
            <div className="flex flex-wrap items-center gap-2">
              <ModelPicker value={reportModel} onChange={setReportModel} label={t('model.report')} width="min-w-[180px]" />
              <Button
                onClick={() => wrap('report', async () => {
                  const r = await api.reviewReport(sid, { language, ...(reportModel ? { model: reportModel } : {}) })
                  setReport(r)
                })}
                disabled={!session.journal_key || !!busy}
              >
                {busy === 'report' ? t('common.running') : t('session.gen_report')}
              </Button>
              <Button
                onClick={() => wrap('ai-detect', async () => {
                  const r = await api.aiDetect(sid, { language, ...(reportModel ? { model: reportModel } : {}) })
                  setAiDet(r)
                })}
                disabled={!!busy}
              >
                {busy === 'ai-detect' ? t('common.running') : t('session.compute_ai')}
              </Button>
            </div>
          ) : null}
        </div>

        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {/* Live SSE progress */}
          <LiveProgressPanel progress={progress} />
          {/* Decision log — semantic cards + tool calls */}
          <div className="rounded-xl border border-zinc-950/10 bg-zinc-50 p-3 dark:border-white/10 dark:bg-zinc-900">
            <Strong className="text-xs">{t('session.decision_log')}</Strong>
            <div className="mt-2 max-h-64 space-y-1.5 overflow-auto">
              {[
                ...(session.decision_log ?? []),
                ...Object.values(toolCalls).flat().map(tc => ({
                  ts: tc.ts ?? 0,
                  kind: 'tool_call' as const,
                  payload: { tool: tc.tool, summary: tc.summary, error: tc.error },
                }))
              ].sort((a, b) => a.ts - b.ts).map((e, i) => (
                <DecisionLogCard key={i} entry={e} />
              ))}
            </div>
          </div>
        </div>

        {/* Reviewer report — collapsible card inside activity section */}
        {report ? <CollapsibleReportView report={report} /> : null}
        {/* AI detection — collapsible card inside activity section */}
        {aiDet ? <CollapsibleAIDetectView result={aiDet} /> : null}
      </section>

      {error ? (
        <Alert open={!!error} onClose={() => setError(null)}>
          <AlertTitle>{t('common.error')}</AlertTitle>
          <AlertBody>
            <Text>{error}</Text>
          </AlertBody>
          <AlertActions>
            <Button onClick={() => setError(null)}>{t('common.dismiss')}</Button>
          </AlertActions>
        </Alert>
      ) : null}
    </div>
  )
}

// ============================================================================
// Subcomponents
// ============================================================================

function ComprehensionView(props: {
  card: ComprehensionCard
  confirmed: boolean
  corrections: string
  onCorrectionsChange: (s: string) => void
  onConfirm: () => void
  busy: string | null
}) {
  const { card, confirmed, corrections, onCorrectionsChange, onConfirm, busy } = props
  const { t } = useI18n()
  return (
    <div className="space-y-3 rounded-xl border border-zinc-950/10 bg-white p-4 dark:border-white/10 dark:bg-zinc-900">
      <div className="flex items-center justify-between">
        <Strong>{card.title}</Strong>
        <Badge color={confirmed ? 'emerald' : 'amber'}>
          {confirmed ? t('session.confirmed_badge') : t('session.awaiting_confirmation')}
        </Badge>
      </div>
      <Text>{card.one_line_summary}</Text>
      <div className="grid grid-cols-1 gap-3 text-sm md:grid-cols-2">
        <div>
          <Strong>{t('session.field')}</Strong>
          <Text>{card.field} / {card.subfield}</Text>
          <Strong className="mt-2 block">{t('session.problem')}</Strong>
          <Text>{card.problem}</Text>
          <Strong className="mt-2 block">{t('session.datasets')}</Strong>
          <Text>{card.datasets_or_benchmarks.join(', ') || '—'}</Text>
        </div>
        <div>
          <Strong>{t('session.contributions')}</Strong>
          <ul className="list-disc pl-5">
            {card.contributions.map((c, i) => <li key={i}>{c}</li>)}
          </ul>
          <Strong className="mt-2 block">{t('session.key_claims')}</Strong>
          <ul className="list-disc pl-5">
            {card.key_claims.map((c, i) => <li key={i}>{c}</li>)}
          </ul>
          {card.open_questions.length > 0 ? (
            <>
              <Strong className="mt-2 block">{t('session.open_questions')}</Strong>
              <ul className="list-disc pl-5 text-amber-700 dark:text-amber-400">
                {card.open_questions.map((q, i) => <li key={i}>{q}</li>)}
              </ul>
            </>
          ) : null}
        </div>
      </div>
      <Text className="text-xs">{t('session.confidence')}: {(card.confidence * 100).toFixed(0)}%</Text>
      <div>
        <label className="mb-1 block text-xs font-medium text-zinc-600 dark:text-zinc-400">
          {t('session.corrections_label')}
        </label>
        <textarea
          rows={3}
          value={corrections}
          onChange={(e) => onCorrectionsChange(e.currentTarget.value)}
          disabled={confirmed}
          placeholder={t('session.corrections_placeholder')}
          className="w-full rounded border border-zinc-300 bg-white px-2.5 py-1.5 text-sm dark:border-zinc-600 dark:bg-zinc-800 disabled:opacity-60"
        />
      </div>
      <div className="flex justify-end">
        <Button color="emerald" onClick={onConfirm} disabled={confirmed || !!busy}>
          {confirmed ? t('session.confirmed') : t('session.confirm_understanding')}
        </Button>
      </div>
    </div>
  )
}

function PlanView({ plan, approved }: { plan: Plan; approved: boolean }) {
  const { t } = useI18n()
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <Badge color={approved ? 'emerald' : 'amber'}>
          {approved ? t('session.approved_badge') : t('session.awaiting_approval')}
        </Badge>
        <Strong>{t('session.strategy')}</Strong>
      </div>
      <Text>{plan.overall_strategy}</Text>
      {plan.risks.length > 0 ? (
        <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm dark:border-amber-500/30 dark:bg-amber-500/10">
          <Strong>{t('session.risks')}</Strong>
          <ul className="mt-1 list-disc pl-5">
            {plan.risks.map((r, i) => <li key={i}>{r}</li>)}
          </ul>
        </div>
      ) : null}
    </div>
  )
}

function TodoTable(props: {
  todos: TodoItem[]
  busy: string | null
  approved: boolean
  progress: Record<
    string,
    { paragraphs_done: number; batch_idx: number; batch_total: number; new: number }
  >
  onRun: (todo: TodoItem) => void
}) {
  const { t } = useI18n()
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-zinc-200 text-left text-xs text-zinc-500 dark:border-zinc-700">
            <th className="pb-2 pr-4 font-medium">{t('session.todo_title')}</th>
            <th className="pb-2 pr-4 font-medium">{t('session.todo_category')}</th>
            <th className="pb-2 pr-4 font-medium">{t('session.todo_priority')}</th>
            <th className="pb-2 pr-4 font-medium">{t('session.todo_status')}</th>
            <th className="pb-2 font-medium">{t('session.todo_run')}</th>
          </tr>
        </thead>
        <tbody>
          {props.todos.map((todo) => {
            const running = props.busy === `edit-${todo.id}`
            const descStr = Array.isArray(todo.description)
              ? todo.description.join('\n')
              : (todo.description ?? '')
            const bullets = descStr ? descStr.split(/\n/).filter(Boolean) : []
            return (
              <tr key={todo.id} className="align-top border-t border-zinc-100 first:border-t-0 dark:border-zinc-800">
                <td className="py-2 pr-4">
                  <Strong>{todo.title}</Strong>
                  {bullets.length > 0 && (
                    <ul className="mt-1 max-w-sm space-y-0.5 text-xs text-zinc-500">
                      {bullets.map((b, i) => (
                        <li key={i} className="flex gap-1">
                          <span className="shrink-0 text-zinc-400">{b.startsWith('-') ? '' : '·'}</span>
                          <span>{b.replace(/^[-*]\s*/, '')}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </td>
                <td className="py-2 pr-4"><Badge color="blue">{toPascal(todo.category)}</Badge></td>
                <td className="py-2 pr-4">
                  <Badge color={todo.priority === 'critical' ? 'red' : todo.priority === 'high' ? 'amber' : 'zinc'}>
                    {toPascal(todo.priority)}
                  </Badge>
                </td>
                <td className="py-2 pr-4"><Badge>{toPascal(todo.status)}</Badge></td>
                <td className="py-2">
                  {todo.needs_human ? (
                    <Badge color="amber">{t('session.needs_human')}</Badge>
                  ) : (
                    <Button
                      onClick={() => props.onRun(todo)}
                      disabled={!!props.busy || !props.approved}
                      title={!props.approved ? t('session.approve_plan_first') : undefined}
                    >
                      {running ? t('common.running') : t('session.run_editor')}
                    </Button>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function SuggestionsView(props: {
  suggestions: Suggestion[]
  busy: string | null
  onDecide: (id: string, d: 'accepted' | 'rejected' | 'modified', modified_after?: string) => void
}) {
  const { t } = useI18n()
  if (props.suggestions.length === 0) {
    return <Text className="text-sm">{t('suggestion.no_suggestions')}</Text>
  }
  return (
    <div className="space-y-3">
      {props.suggestions.map((s) => (
        <SuggestionCard key={s.id} s={s} onDecide={props.onDecide} busy={props.busy} />
      ))}
    </div>
  )
}

// ── word-level diff ──────────────────────────────────────────────────────────
type DiffToken = { type: 'eq' | 'del' | 'ins'; text: string }

function _lcs(a: string[], b: string[]): number[][] {
  const m = a.length, n = b.length
  const dp = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0))
  for (let i = 1; i <= m; i++)
    for (let j = 1; j <= n; j++)
      dp[i][j] = a[i - 1] === b[j - 1] ? dp[i - 1][j - 1] + 1 : Math.max(dp[i - 1][j], dp[i][j - 1])
  return dp
}

function wordDiff(before: string, after: string): DiffToken[] {
  if (before.length > 2000 || after.length > 2000) {
    return [{ type: 'del', text: before }, { type: 'ins', text: after }]
  }
  const a = before.match(/\S+|\s+/g) ?? []
  const b = after.match(/\S+|\s+/g) ?? []
  const dp = _lcs(a, b)
  const ops: DiffToken[] = []
  let i = a.length, j = b.length
  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && a[i - 1] === b[j - 1]) {
      ops.unshift({ type: 'eq', text: a[i - 1] }); i--; j--
    } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
      ops.unshift({ type: 'ins', text: b[j - 1] }); j--
    } else {
      ops.unshift({ type: 'del', text: a[i - 1] }); i--
    }
  }
  return ops
}

function WordDiff({ before, after }: { before: string; after: string }) {
  const ops = wordDiff(before, after)
  return (
    <div className="mt-1 whitespace-pre-wrap font-mono text-xs leading-relaxed">
      {ops.map((op, i) => {
        if (op.type === 'eq') return <span key={i}>{op.text}</span>
        if (op.type === 'del') return (
          <span key={i} className="bg-red-100 text-red-700 line-through dark:bg-red-900/30 dark:text-red-400">{op.text}</span>
        )
        return (
          <span key={i} className="bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400">{op.text}</span>
        )
      })}
    </div>
  )
}
// ─────────────────────────────────────────────────────────────────────────────

function SuggestionCard(props: {
  s: Suggestion
  busy: string | null
  onDecide: (id: string, d: 'accepted' | 'rejected' | 'modified', modified_after?: string) => void
}) {
  const { s, busy, onDecide } = props
  const { t } = useI18n()
  const [editing, setEditing] = useState(false)
  const [edited, setEdited] = useState(s.user_modified_after ?? s.after)
  return (
    <div
      className="space-y-2 rounded-xl border border-zinc-950/10 bg-white p-4 text-sm dark:border-white/10 dark:bg-zinc-900"
      data-suggestion-paragraph={s.paragraph_id}
      id={`sug-${s.id}`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <Badge color={sevColor[s.severity] ?? 'zinc'}>{toPascal(s.severity)}</Badge>
        <Badge color="blue">{toPascal(s.category)}</Badge>
        <StatusBadge status={s.status} />
        {s.flag_for_user ? (
          <Badge color="red">⚠ touches numbers / citations</Badge>
        ) : null}
        <span className="ml-auto font-mono text-xs text-zinc-500">{s.paragraph_id}</span>
      </div>

      <div className="space-y-2">
        <div className="rounded-md border border-zinc-200 bg-zinc-50 p-2 dark:border-zinc-700 dark:bg-zinc-800">
          <Strong className="text-xs text-zinc-500">{t('suggestion.diff')}</Strong>
          <WordDiff before={s.before} after={editing ? edited : s.after} />
        </div>
        {editing && (
          <div className="rounded-md border border-emerald-300 bg-emerald-50 p-2 dark:border-emerald-500/30 dark:bg-emerald-500/10">
            <Strong className="text-xs">{t('suggestion.after')}</Strong>
            <Textarea
              rows={3}
              value={edited}
              onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setEdited(e.target.value)}
            />
          </div>
        )}
      </div>

      <Text className="text-xs">
        <Strong>{t('suggestion.why')}:</Strong> {s.rationale}
      </Text>

      {s.numeric_warnings.length > 0 ? (
        <div className="rounded-md border border-amber-300 bg-amber-50 p-2 text-xs dark:border-amber-500/30 dark:bg-amber-500/10">
          <Strong>{t('suggestion.number_guard')}</Strong>
          <ul className="list-disc pl-5">
            {s.numeric_warnings.map((w, i) => (
              <li key={i}>
                <Badge color={w.severity === 'critical' ? 'red' : 'amber'}>{w.kind}</Badge>{' '}
                +[{w.added.join(', ')}] −[{w.removed.join(', ')}]
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="flex flex-wrap gap-2">
        <Button
          color="emerald"
          onClick={() => onDecide(s.id, 'accepted')}
          disabled={!!busy || s.status !== 'pending'}
        >
          {t('common.accept')}
        </Button>
        <Button
          color="red"
          onClick={() => onDecide(s.id, 'rejected')}
          disabled={!!busy || s.status !== 'pending'}
        >
          {t('common.reject')}
        </Button>
        {editing ? (
          <>
            <Button
              color="emerald"
              onClick={() => {
                onDecide(s.id, 'modified', edited)
                setEditing(false)
              }}
              disabled={!!busy}
            >
              {t('suggestion.save_mod')}
            </Button>
            <Button onClick={() => setEditing(false)}>{t('common.cancel')}</Button>
          </>
        ) : (
          <Button onClick={() => setEditing(true)} disabled={!!busy || s.status !== 'pending'}>
            {t('common.modify')}
          </Button>
        )}
      </div>
    </div>
  )
}

// ── Decision log semantic card ───────────────────────────────────────────────
type LogEntry = { ts: number; kind: string; payload: Record<string, unknown> }

const LOG_COLOR: Record<string, 'emerald' | 'blue' | 'amber' | 'red' | 'zinc' | 'violet'> = {
  comprehension_generated: 'blue',
  comprehension_confirmed: 'emerald',
  journal_ranked: 'violet',
  journal_set: 'violet',
  plan_generated: 'amber',
  plan_approved: 'emerald',
  todo_started: 'blue',
  todo_status: 'blue',
  todo_done: 'emerald',
  review_report_generated: 'amber',
  suggestion_accepted: 'emerald',
  suggestion_rejected: 'red',
  suggestion_modified: 'blue',
  compact: 'zinc',
  tool_call: 'zinc',
}

function DecisionLogCard({ entry }: { entry: LogEntry }) {
  const { t } = useI18n()
  const color = LOG_COLOR[entry.kind] ?? 'zinc'
  const label = t(`log.${entry.kind}` as Parameters<typeof t>[0]) ?? entry.kind
  const p = entry.payload ?? {}
  let detail = ''
  switch (entry.kind) {
    case 'comprehension_generated':
      detail = `${p.title ?? ''} · ${t('log.payload.conf')} ${p.confidence ?? ''}`; break
    case 'comprehension_confirmed':
      detail = p.corrections ? `"${String(p.corrections).slice(0, 60)}"` : '—'; break
    case 'journal_ranked':
      detail = `${t('log.payload.top')}: ${p.top_pick ?? '?'}`; break
    case 'journal_set':
      detail = String(p.journal_key ?? '?'); break
    case 'plan_generated':
      detail = `${p.n_todos ?? 0} ${t('log.payload.todos')} · ${p.risks ?? 0} ${t('log.payload.risks')}`; break
    case 'plan_approved':
      detail = `${p.n_todos ?? 0} ${t('log.payload.todos')}`; break
    case 'todo_started': case 'todo_status': case 'todo_done':
      detail = `${p.todo_id ?? ''} → ${p.status ?? p.notes ?? ''}`; break
    case 'review_report_generated':
      detail = `${p.recommendation ?? ''} · ${t('log.payload.score')} ${p.overall ?? '?'}`; break
    case 'suggestion_accepted': case 'suggestion_rejected': case 'suggestion_modified':
      detail = String(p.suggestion_id ?? p.id ?? ''); break
    case 'tool_call':
      detail = p.error
        ? `❌ ${p.tool} — ${String(p.error).slice(0, 80)}`
        : `${p.tool}${p.summary ? ` — ${String(p.summary).slice(0, 80)}` : ''}`
      break
    default:
      detail = Object.entries(p).map(([k, v]) => `${k}: ${v}`).join(' · ').slice(0, 80)
  }
  const time = new Date(entry.ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  return (
    <div className="flex items-start gap-2 rounded-md border border-zinc-200 bg-white px-2 py-1.5 dark:border-zinc-700 dark:bg-zinc-800">
      <Badge color={color} className="shrink-0 mt-0.5">{label}</Badge>
      <div className="min-w-0 flex-1">
        <span className="text-xs text-zinc-600 dark:text-zinc-300 break-all">{detail}</span>
      </div>
      <span className="shrink-0 font-mono text-xs text-zinc-400">{time}</span>
    </div>
  )
}
// ─────────────────────────────────────────────────────────────────────────────

// Map backend stage keys to display names
const STAGE_LABEL: Record<string, string> = {
  comprehend: 'Comprehension', plan: 'Planning', edit: 'Editing',
  review_report: 'Review Report', ai_detect: 'AI Detection', compact: 'Memory Compact',
}

function parseLiveEvent(m: SSEMessage): { icon: string; label: string; color: 'emerald' | 'blue' | 'amber' | 'red' | 'zinc' } {
  if (m.event === 'ready') return { icon: '✓', label: 'Connected', color: 'emerald' }
  if (m.event !== 'progress') return { icon: '·', label: m.data.slice(0, 80), color: 'zinc' }
  try {
    const p = JSON.parse(m.data)
    const stage = STAGE_LABEL[p.stage as string] ?? (p.stage as string) ?? ''
    switch (p.kind as string) {
      case 'stage_started': return { icon: '▶', label: `${stage}…`, color: 'blue' }
      case 'stage_done':    return { icon: '✓', label: `${stage} done`, color: 'emerald' }
      case 'edit_batch': {
        const title = (p.todo_title as string)?.slice(0, 40) ?? p.todo_id
        const batch = `${(p.batch_idx as number) + 1}/${p.batch_total}`
        const news = p.new_suggestions ? ` +${p.new_suggestions}` : ''
        return { icon: '✎', label: `${title} · batch ${batch}${news}`, color: 'blue' }
      }
      case 'tool_call': {
        const summary = (p.summary as string)?.slice(0, 60) ?? ''
        return { icon: '🔧', label: `${p.tool}${summary ? ` — ${summary}` : ''}`, color: 'zinc' }
      }
      case 'compact': return { icon: '⚡', label: `Memory compacted (+${p.n_new ?? 0})`, color: 'amber' }
      default: {
        const stage2 = (p.stage as string) ?? (p.todo_title as string) ?? ''
        return { icon: '·', label: stage2 || m.data.slice(0, 80), color: 'zinc' }
      }
    }
  } catch {
    return { icon: '·', label: m.data.slice(0, 80), color: 'zinc' }
  }
}

function LiveProgressPanel({ progress }: { progress: SSEMessage[] }) {
  const { t } = useI18n()
  const scrollRef = useRef<HTMLDivElement>(null)
  const visible = progress.filter(m => m.event !== 'ping')
  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }, [visible.length])
  return (
    <div className="rounded-xl border border-zinc-950/10 bg-zinc-50 p-3 dark:border-white/10 dark:bg-zinc-900">
      <Strong className="text-xs">{t('session.live')}</Strong>
      <div ref={scrollRef} className="mt-2 max-h-64 space-y-1 overflow-auto">
        {visible.length === 0 ? (
          <p className="text-xs text-zinc-400">{t('log.no_live_events')}</p>
        ) : visible.map((m, i) => {
          const { icon, label, color } = parseLiveEvent(m)
          return (
            <div key={i} className="flex items-start gap-2 rounded-md px-2 py-1 odd:bg-zinc-100 dark:odd:bg-zinc-800">
              <Badge color={color} className="shrink-0 mt-0.5">{icon}</Badge>
              <span className="text-xs text-zinc-600 dark:text-zinc-400 break-all">{label}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function CollapsibleReportView({ report }: { report: ReviewReport }) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const recKey = `report.${report.recommendation.replace(/-/g, '_')}` as Parameters<typeof t>[0]
  const recLabel = t(recKey) ?? report.recommendation
  const color = report.recommendation === 'accept' ? 'emerald'
    : report.recommendation === 'reject' ? 'red' : 'amber'
  return (
    <div className="rounded-xl border border-zinc-950/10 bg-white dark:border-white/10 dark:bg-zinc-900">
      <button
        type="button"
        className="flex w-full items-center gap-3 px-4 py-3 text-left"
        onClick={() => setOpen(v => !v)}
      >
        <Badge color={color as 'emerald' | 'red' | 'amber'}>{recLabel}</Badge>
        <Strong className="flex-1 text-sm">{t('session.report_ai')}</Strong>
        <Strong className="text-sm">{report.scores.overall ?? '—'}/10</Strong>
        <span className="text-xs text-zinc-400">{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <div className="border-t border-zinc-100 px-4 pb-4 pt-3 dark:border-zinc-800">
          <ReportView report={report} />
        </div>
      )}
    </div>
  )
}

function CollapsibleAIDetectView({ result }: { result: AIDetectionResult }) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const color = result.ai_likelihood >= 70 ? 'red' : result.ai_likelihood >= 40 ? 'amber' : 'emerald'
  const verdictKey = `aidet.verdict.${result.verdict}` as Parameters<typeof t>[0]
  const verdictLabel = t(verdictKey) ?? toTitle(result.verdict)
  return (
    <div className="rounded-xl border border-zinc-950/10 bg-white dark:border-white/10 dark:bg-zinc-900">
      <button
        type="button"
        className="flex w-full items-center gap-3 px-4 py-3 text-left"
        onClick={() => setOpen(v => !v)}
      >
        <Badge color={color}>{verdictLabel}</Badge>
        <Strong className="flex-1 text-sm">{t('aidet.likelihood')}</Strong>
        <Strong className="text-sm">{result.ai_likelihood}/100</Strong>
        <span className="text-xs text-zinc-400">{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <div className="border-t border-zinc-100 px-4 pb-4 pt-3 dark:border-zinc-800">
          <AIDetectView result={result} />
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────

function ReportView({ report }: { report: ReviewReport }) {
  const { t } = useI18n()
  const recKey = `report.${report.recommendation.replace(/-/g, '_')}` as Parameters<typeof t>[0]
  const recLabel = t(recKey) ?? report.recommendation
  return (
    <div className="space-y-3 rounded-xl border border-zinc-950/10 bg-white p-4 dark:border-white/10 dark:bg-zinc-900">
      <div className="flex flex-wrap items-center gap-2">
        <Badge color="blue">{recLabel}</Badge>
        <Strong>{t('report.overall')}: {report.scores.overall ?? '—'} / 10</Strong>
      </div>
      <Text>{report.summary}</Text>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <div>
          <Strong>{t('report.strengths')}</Strong>
          <ul className="list-disc pl-5 text-sm">
            {report.strengths.map((s, i) => <li key={i}>{s}</li>)}
          </ul>
        </div>
        <div>
          <Strong>{t('report.weaknesses')}</Strong>
          <ul className="list-disc pl-5 text-sm">
            {report.weaknesses.map((s, i) => <li key={i}>{s}</li>)}
          </ul>
        </div>
      </div>

      <div>
        <Strong>{t('report.scores')}</Strong>
        <div className="mt-1 grid grid-cols-2 gap-2 text-sm md:grid-cols-3">
          {Object.entries(report.scores).map(([k, v]) => (
            <div key={k} className="rounded border border-zinc-200 px-2 py-1 dark:border-zinc-700">
              {toTitle(k)}: <Strong>{v}</Strong>
            </div>
          ))}
        </div>
      </div>

      {report.experiments_to_strengthen.length > 0 ? (
        <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm dark:border-amber-500/30 dark:bg-amber-500/10">
          <Strong>{t('report.experiments_hint')}</Strong>
          <ul className="mt-1 list-disc pl-5">
            {report.experiments_to_strengthen.map((e, i) => (
              <li key={i}>
                <Badge color={e.priority === 'high' ? 'red' : e.priority === 'medium' ? 'amber' : 'zinc'}>
                  {t(`common.priority.${e.priority}` as Parameters<typeof t>[0]) ?? toTitle(e.priority)}
                </Badge>{' '}
                <Strong>{e.claim}</Strong> — {e.suggested_experiment}
                {e.rationale ? <div className="text-xs text-zinc-500">{e.rationale}</div> : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {report.compliance_check.length > 0 ? (
        <div>
          <Strong>{t('report.compliance')}</Strong>
          <Table dense>
            <TableHead>
              <TableRow>
                <TableHeader>{t('report.rule')}</TableHeader>
                <TableHeader>{t('report.status')}</TableHeader>
                <TableHeader>{t('report.note')}</TableHeader>
              </TableRow>
            </TableHead>
            <TableBody>
              {report.compliance_check.map((c, i) => (
                <TableRow key={i}>
                  <TableCell className="text-xs">{c.rule}</TableCell>
                  <TableCell>
                    <Badge color={c.status === 'ok' ? 'emerald' : c.status === 'violated' ? 'red' : 'amber'}>
                      {t(`report.status.${c.status}` as Parameters<typeof t>[0]) ?? toTitle(c.status)}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-xs">{c.note}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      ) : null}

      {report.decision_letter_draft ? (
        <div>
          <Strong>{t('report.decision_letter')}</Strong>
          <pre className="mt-1 whitespace-pre-wrap rounded border border-zinc-200 bg-zinc-50 p-3 text-sm dark:border-zinc-700 dark:bg-zinc-800">
            {report.decision_letter_draft}
          </pre>
        </div>
      ) : null}
    </div>
  )
}

function AIDetectView({ result }: { result: AIDetectionResult }) {
  const { t } = useI18n()
  const color = result.ai_likelihood >= 70 ? 'red' : result.ai_likelihood >= 40 ? 'amber' : 'emerald'
  const verdictKey = `aidet.verdict.${result.verdict}` as Parameters<typeof t>[0]
  const verdictLabel = t(verdictKey) ?? toTitle(result.verdict)
  return (
    <div className="space-y-2 rounded-xl border border-zinc-950/10 bg-white p-4 text-sm dark:border-white/10 dark:bg-zinc-900">
      <div className="flex items-center gap-3">
        <Badge color={color}>{verdictLabel}</Badge>
        <Strong>{t('aidet.likelihood')}: {result.ai_likelihood} / 100</Strong>
        <span className="text-xs text-zinc-500">{t('aidet.stateless')}</span>
      </div>
      {result.top_signals.length > 0 ? (
        <div>
          <Strong>{t('aidet.signals')}</Strong>
          <ul className="list-disc pl-5">
            {result.top_signals.map((s, i) => <li key={i}>{s}</li>)}
          </ul>
        </div>
      ) : null}
      {result.examples.length > 0 ? (
        <div>
          <Strong>{t('aidet.examples')}</Strong>
          <ul className="space-y-1">
            {result.examples.map((e, i) => (
              <li key={i} className="rounded border border-zinc-200 p-2 dark:border-zinc-700">
                <pre className="whitespace-pre-wrap font-mono text-xs">"{e.snippet}"</pre>
                <Text className="text-xs">{e.why}</Text>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {result.advice ? <Text><Strong>{t('aidet.advice')}:</Strong> {result.advice}</Text> : null}
    </div>
  )
}
