// API client for the paper-agent FastAPI backend.
// All endpoints accept/return JSON; uploads use multipart/form-data.

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? 'http://127.0.0.1:8765'

async function request<T>(
  path: string,
  init?: RequestInit & { json?: unknown },
): Promise<T> {
  const headers = new Headers(init?.headers)
  let body = init?.body
  if (init?.json !== undefined) {
    headers.set('Content-Type', 'application/json')
    body = JSON.stringify(init.json)
  }
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers, body })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`${res.status} ${res.statusText}: ${text}`)
  }
  return (await res.json()) as T
}

// --------- types (kept loose; backend is the source of truth) -----------

export type SessionSummary = {
  id: string
  journal_key: string
  source_type: 'latex' | 'docx' | string
  created_at: number
  plan_approved: boolean
  n_suggestions: number
  n_accepted: number
  n_pending: number
}

export type SkillArticleType = {
  type: string
  word_limit: number | null
  abstract_limit: number | null
  figures_max: number | null
  tables_max: number | null
  references_max: number | null
  pages_max: number | null
  notes: string
}

export type SkillSummary = {
  key: string
  name: string
  publisher: string
  url: string
  impact_factor: number | null
  open_access: boolean
  disciplines: string[]
  scope: string
  scope_keywords: string[]
  required_sections: string[]
  article_types: SkillArticleType[]
}

export type SkillDetail = SkillSummary & {
  structure_rules: string[]
  content_rules: string[]
  compliance_rules: string[]
  language_rules: string[]
  declarations: string[]
  reference_style: string
  reference_format: string
  submission_url: string
  figures_notes: string
  sections_notes: string
}

export type TocEntry = { id: string; level: number; title: string }

export type DocStructureSection = {
  id: string; level: number; title: string; n_paras: number; n_words: number
}
export type DocStructure = {
  title: string
  source_type: string
  has_abstract: boolean
  abstract_words: number
  n_references: number
  sections: DocStructureSection[]
  stats: { sections: number; paragraphs: number; sentences: number; words: number; references: number }
}

export type UploadResult = {
  session_id: string
  source_type: 'latex' | 'docx'
  stats: Record<string, number>
  toc: TocEntry[]
  title: string
}

export type ComprehensionCard = {
  title: string
  one_line_summary: string
  field: string
  subfield: string
  problem: string
  contributions: string[]
  methods: string[]
  key_claims: string[]
  datasets_or_benchmarks: string[]
  limitations_self_stated: string[]
  confidence: number
  open_questions: string[]
}

export type TodoItem = {
  id: string
  category: string
  priority: string
  title: string
  description: string | string[]
  target_section_ids: string[]
  target_paragraph_ids: string[]
  expected_outcome: string
  status: string
  notes: string
  needs_human?: boolean
}

export type Plan = {
  overall_strategy: string
  risks: string[]
  todos: TodoItem[]
  journal_target?: string | null
}

export type Suggestion = {
  id: string
  todo_id: string
  paragraph_id: string
  section_id: string
  category: string
  severity: string
  before: string
  after: string
  rationale: string
  flag_for_user: boolean
  numeric_warnings: { kind: string; added: string[]; removed: string[]; severity: string }[]
  status: string
  user_modified_after?: string | null
}

export type SessionDoc = {
  id: string
  journal_key: string
  source_path: string
  source_type: 'latex' | 'docx'
  comprehension: ComprehensionCard | null
  comprehension_confirmed: boolean
  user_corrections: string
  plan: Plan | null
  plan_approved: boolean
  suggestions: Record<string, Suggestion>
  decision_log: { ts: number; kind: string; payload: Record<string, unknown> }[]
  memory: {
    compact_summary: string
    user_preferences: string[]
    rejected_patterns: { pattern: string; reason: string }[]
    consistency_notes: { term: string; rule: string }[]
    outstanding_todos: string[]
    completed_todos: string[]
    manual_overrides: string[]
  }
  review_report: ReviewReport | null
  ai_detection: AIDetectionResult | null
}

export type ReviewReport = {
  summary: string
  strengths: string[]
  weaknesses: string[]
  scores: Record<string, number>
  recommendation: string
  experiments_to_strengthen: {
    claim: string
    suggested_experiment: string
    priority: string
    rationale?: string
  }[]
  compliance_check: { rule: string; status: string; note: string }[]
  decision_letter_draft: string
}

export type AIDetectionResult = {
  ai_likelihood: number
  verdict: string
  top_signals: string[]
  examples: { snippet: string; why: string }[]
  advice: string
}

export type JournalRanking = {
  ranked: {
    journal_key: string
    journal_name: string
    score: number
    fit_reasons: string[]
    concerns: string[]
    recommended_article_type: string
  }[]
  top_pick: string
  rationale: string
}

// ----------------------- endpoints ---------------------------------------

export const api = {
  health: () => request<{ ok: boolean; version: string }>('/api/health'),

  listModels: () =>
    request<{
      models: string[]
      presets: { fast: string; smart: string; deep: string }
    }>('/api/models'),

  getConfig: () =>
    request<{
      api_key_masked: string
      api_key_set: boolean
      base_url: string
      fast_model: string
      smart_model: string
      deep_model: string
    }>('/api/config'),

  updateConfig: (patch: {
    api_key?: string
    base_url?: string
    fast_model?: string
    smart_model?: string
    deep_model?: string
  }) =>
    request<{
      api_key_masked: string
      api_key_set: boolean
      base_url: string
      fast_model: string
      smart_model: string
      deep_model: string
    }>('/api/config', { method: 'POST', json: patch }),

  testConfig: () =>
    request<{ ok: boolean; model_count?: number; sample?: string[]; error?: string }>(
      '/api/config/test',
      { method: 'POST' },
    ),

  listSkills: () => request<{ skills: SkillSummary[] }>('/api/skills'),

  setJournal: (sid: string, journal_key: string) =>
    request<{ ok: boolean; journal_key: string }>(
      `/api/sessions/${sid}/set_journal`,
      { method: 'POST', json: { journal_key } },
    ),

  getPreview: (sid: string) =>
    request<{
      title: string
      source_type: 'latex' | 'docx'
      blocks: (
        | { kind: 'abstract'; id: string; text: string; raw?: string }
        | { kind: 'heading'; id: string; level: number; title: string }
        | {
            kind: 'paragraph'
            id: string
            section_id: string
            text: string
            raw?: string
          }
      )[]
      stats: Record<string, number>
    }>(`/api/sessions/${sid}/preview`),

  logHistory: (limit = 1000, offset = 0) =>
    request<{ lines: string[] }>(
      `/api/logs/history?limit=${limit}&offset=${offset}`,
    ),

  upload: (file: File, journalKey = '') => {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('journal_key', journalKey)
    return request<UploadResult>('/api/upload', { method: 'POST', body: fd })
  },

  getSession: (sid: string) => request<SessionDoc>(`/api/sessions/${sid}`),

  getSource: (sid: string) =>
    request<{
      source_type: string
      title: string
      abstract: string
      toc: TocEntry[]
      source_text: string
    }>(`/api/sessions/${sid}/source`),

  comprehend: (
    sid: string,
    opts: { tier?: string; model?: string } = {},
  ) =>
    request<{ comprehension: ComprehensionCard }>(
      `/api/sessions/${sid}/comprehend`,
      { method: 'POST', json: { tier: 'smart', ...opts } },
    ),

  confirmComprehension: (sid: string, user_corrections = '') =>
    request<{ ok: boolean }>(
      `/api/sessions/${sid}/comprehension/confirm`,
      { method: 'POST', json: { user_corrections } },
    ),

  predictJournal: (sid: string, candidates?: string[]) =>
    request<JournalRanking>(`/api/sessions/${sid}/predict_journal`, {
      method: 'POST',
      json: { candidates },
    }),

  makePlan: (sid: string, opts: { tier?: string; model?: string } = {}) =>
    request<{ plan: Plan }>(`/api/sessions/${sid}/plan`, {
      method: 'POST',
      json: { tier: 'deep', ...opts },
    }),

  approvePlan: (sid: string, edited?: Plan) =>
    request<{ ok: boolean; plan: Plan }>(
      `/api/sessions/${sid}/plan/approve`,
      { method: 'POST', json: { edited_plan: edited ?? null } },
    ),

  runEditor: (
    sid: string,
    todoId: string,
    opts: { language?: string; tier?: string; model?: string; use_tools?: boolean } = {},
  ) =>
    request<{ todo_id: string; suggestions: Suggestion[]; notes: string[] }>(
      `/api/sessions/${sid}/edit/${todoId}`,
      {
        method: 'POST',
        json: {
          language: 'en',
          tier: 'smart',
          ...(opts.model ? { model: opts.model } : {}),
          ...opts,
        },
      },
    ),

  autoGrammar: (sid: string, opts: { language?: string; tier?: string } = {}) =>
    request<{ suggestions: Suggestion[] }>(
      `/api/sessions/${sid}/auto_grammar`,
      { method: 'POST', json: { language: 'en', tier: 'fast', ...opts } },
    ),

  decide: (
    sid: string,
    suggestion_id: string,
    decision: 'accepted' | 'rejected' | 'modified',
    modified_after?: string,
  ) =>
    request<{ ok: boolean }>(`/api/sessions/${sid}/decide`, {
      method: 'POST',
      json: { suggestion_id, decision, modified_after },
    }),

  compact: (sid: string) =>
    request<{ memory: SessionDoc['memory'] }>(`/api/sessions/${sid}/compact`, {
      method: 'POST',
    }),

  reviewReport: (
    sid: string,
    opts: { language?: string; tier?: string; model?: string } = {},
  ) =>
    request<ReviewReport>(`/api/sessions/${sid}/review_report`, {
      method: 'POST',
      json: { language: 'en', tier: 'deep', ...opts },
    }),

  aiDetect: (sid: string, opts: { language?: string; tier?: string } = {}) =>
    request<AIDetectionResult>(`/api/sessions/${sid}/ai_detect`, {
      method: 'POST',
      json: { language: 'en', tier: 'smart', ...opts },
    }),

  exportFile: (sid: string, format: 'latex' | 'docx', author = 'Paper-Agent AI') =>
    request<{
      summary: {
        accepted: number
        modified: number
        pending: number
        rejected: number
        skipped_not_found: number
        flagged_pending: string[]
        written_path: string
      }
      download_url: string
      page_warnings?: string[]
    }>(
      `/api/sessions/${sid}/export?format=${format}&author=${encodeURIComponent(author)}`,
    ),

  downloadUrl: (sid: string, format: 'latex' | 'docx') =>
    `${API_BASE}/api/sessions/${sid}/export/file?format=${format}`,

  listSessions: () =>
    request<{ sessions: SessionSummary[] }>('/api/sessions'),

  getSkill: (key: string) =>
    request<SkillDetail>(`/api/skills/${key}`),

  getStructure: (sid: string) =>
    request<DocStructure>(`/api/sessions/${sid}/structure`),

  createSkill: (key: string, yaml_content: string) =>
    request<{ ok: boolean; skill: SkillSummary }>('/api/skills', {
      method: 'POST',
      json: { key, yaml_content },
    }),

  recentLogs: () => request<{ lines: string[] }>('/api/logs'),

  // SSE helpers below open EventSource directly; not via fetch.
  logsStreamUrl: () => `${API_BASE}/api/logs/stream`,
  progressStreamUrl: (sid: string) =>
    `${API_BASE}/api/sessions/${sid}/progress`,
}
