'use client'

import { useEffect, useState, useMemo } from 'react'
import { api, type SkillSummary, type SkillDetail, type SkillArticleType } from '@/lib/api'
import { useI18n } from '@/lib/i18n'
import { Badge } from '@/components/badge'
import { Button } from '@/components/button'
import { Input } from '@/components/input'
import { Textarea } from '@/components/textarea'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/table'
import { Heading, Subheading } from '@/components/heading'
import { Text } from '@/components/text'

// ─── helpers ────────────────────────────────────────────────────────────────

function fmt(n: number | null | undefined, unit = '') {
  if (n == null) return '—'
  return unit ? `${n} ${unit}` : String(n)
}

// ─── visual form fields for new/edit skill ─────────────────────────────────

type VisualForm = {
  name: string; publisher: string; url: string; if_: string; open_access: boolean
  disciplines: string; scope: string; keywords: string
  word_limit: string; abstract_limit: string; figures_max: string; tables_max: string
  references_max: string; pages_max: string
  required_sections: string; optional_sections: string
  structure_rules: string; content_rules: string; compliance_rules: string; language_rules: string
}

const BLANK_FORM: VisualForm = {
  name: '', publisher: '', url: '', if_: '', open_access: true,
  disciplines: '', scope: '', keywords: '',
  word_limit: '8000', abstract_limit: '250', figures_max: '10', tables_max: '5',
  references_max: '60', pages_max: '',
  required_sections: 'Abstract, Introduction, Methods, Results, Discussion',
  optional_sections: 'Conclusion, Supplementary',
  structure_rules: '', content_rules: '', compliance_rules: '', language_rules: '',
}

function formToYaml(f: VisualForm, key: string): string {
  const yamlList = (s: string) =>
    s.split(',').map(v => v.trim()).filter(Boolean).map(v => `    - "${v}"`).join('\n') || '    []'
  const ruleList = (s: string) =>
    s.split('\n').map(v => v.trim()).filter(Boolean).map(v => `    - "${v.replace(/"/g, "'")}"`).join('\n') || '    []'
  return `journal:
  name: "${f.name}"
  abbreviation: "${key}"
  publisher: "${f.publisher}"
  url: "${f.url}"
  impact_factor: ${f.if_ ? f.if_ : 'null'}
  open_access: ${f.open_access}
  discipline:
${yamlList(f.disciplines)}

scope:
  description: |
    ${f.scope.replace(/\n/g, '\n    ')}
  keywords:
${yamlList(f.keywords)}

article_types:
  - type: "Article"
    word_limit: ${f.word_limit || 'null'}
    word_limit_scope: "main text"
    abstract_limit: ${f.abstract_limit || 'null'}
    abstract_type: "structured"
    figures_max: ${f.figures_max || 'null'}
    tables_max: ${f.tables_max || 'null'}
    references_max: ${f.references_max || 'null'}
    pages_max: ${f.pages_max || 'null'}
    notes: ""

format:
  reference_style: "numbered"
  reference_format: ""
  keywords_required: true
  keywords_count: 5

sections:
  required:
${yamlList(f.required_sections)}
  optional:
${yamlList(f.optional_sections)}

agents:
  structure_rules:
${ruleList(f.structure_rules)}
  content_rules:
${ruleList(f.content_rules)}
  compliance_rules:
${ruleList(f.compliance_rules)}
  language_rules:
${ruleList(f.language_rules)}
`
}

function VisualEditor({ form, onChange }: { form: VisualForm; onChange: (f: VisualForm) => void }) {
  const set = (k: keyof VisualForm) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    onChange({ ...form, [k]: e.target.type === 'checkbox' ? (e.target as HTMLInputElement).checked : e.target.value })
  const inp = (label: string, k: keyof VisualForm, placeholder = '') => (
    <div>
      <label className="mb-0.5 block text-xs font-medium text-zinc-500">{label}</label>
      <Input type="text" value={String(form[k])} onChange={set(k)} placeholder={placeholder} />
    </div>
  )
  const ta = (label: string, k: keyof VisualForm, rows = 2, hint = '') => (
    <div>
      <label className="mb-0.5 block text-xs font-medium text-zinc-500">{label}{hint && <span className="ml-1 font-normal text-zinc-400">{hint}</span>}</label>
      <Textarea value={String(form[k])} onChange={set(k)} rows={rows} />
    </div>
  )
  return (
    <div className="space-y-3">
      <p className="text-xs font-semibold uppercase tracking-wide text-zinc-400">Journal info</p>
      <div className="grid grid-cols-2 gap-3">
        {inp('Name', 'name', 'Journal of …')}
        {inp('Publisher', 'publisher')}
        {inp('URL', 'url', 'https://…')}
        {inp('Impact factor', 'if_', 'e.g. 5.2')}
      </div>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={form.open_access} onChange={set('open_access')} />
        Open Access
      </label>
      {inp('Disciplines', 'disciplines', 'biology, chemistry (comma-separated)')}
      {ta('Scope description', 'scope', 3)}
      {inp('Scope keywords', 'keywords', 'protein, gene expression (comma-separated)')}

      <p className="pt-1 text-xs font-semibold uppercase tracking-wide text-zinc-400">Article limits ("Article" type)</p>
      <div className="grid grid-cols-3 gap-3">
        {inp('Word limit', 'word_limit', '8000')}
        {inp('Abstract limit', 'abstract_limit', '250')}
        {inp('Figures max', 'figures_max', '10')}
        {inp('Tables max', 'tables_max', '5')}
        {inp('References max', 'references_max', '60')}
        {inp('Pages max', 'pages_max', 'leave blank if none')}
      </div>

      <p className="pt-1 text-xs font-semibold uppercase tracking-wide text-zinc-400">Sections</p>
      {inp('Required sections', 'required_sections', 'Abstract, Introduction, …')}
      {inp('Optional sections', 'optional_sections')}

      <p className="pt-1 text-xs font-semibold uppercase tracking-wide text-zinc-400">Agent rules (one per line)</p>
      {ta('Structure rules', 'structure_rules', 2, '(one rule per line)')}
      {ta('Content rules', 'content_rules', 2, '(one rule per line)')}
      {ta('Compliance rules', 'compliance_rules', 2, '(one rule per line)')}
      {ta('Language rules', 'language_rules', 2, '(one rule per line)')}
    </div>
  )
}

function DisciplineBadge({
  tag,
  active,
  onClick,
}: {
  tag: string
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-full px-2.5 py-0.5 text-xs font-medium transition ${
        active
          ? 'bg-blue-600 text-white'
          : 'bg-zinc-100 text-zinc-600 hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700'
      }`}
    >
      {tag.replace(/_/g, ' ')}
    </button>
  )
}

function ArticleTypeTable({ types }: { types: SkillArticleType[] }) {
  if (types.length === 0) return null
  return (
    <div className="overflow-x-auto">
      <Table dense>
        <TableHead>
          <TableRow>
            <TableHeader>Type</TableHeader>
            <TableHeader>Words</TableHeader>
            <TableHeader>Abstract</TableHeader>
            <TableHeader>Figs</TableHeader>
            <TableHeader>Tables</TableHeader>
            <TableHeader>Refs</TableHeader>
            <TableHeader>Pages</TableHeader>
          </TableRow>
        </TableHead>
        <TableBody>
          {types.map((t) => (
            <TableRow key={t.type}>
              <TableCell className="font-medium">{t.type}</TableCell>
              <TableCell>{fmt(t.word_limit)}</TableCell>
              <TableCell>{fmt(t.abstract_limit)}</TableCell>
              <TableCell>{fmt(t.figures_max)}</TableCell>
              <TableCell>{fmt(t.tables_max)}</TableCell>
              <TableCell>{fmt(t.references_max)}</TableCell>
              <TableCell className={t.pages_max ? 'font-semibold text-amber-600' : 'text-zinc-400'}>
                {fmt(t.pages_max)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {types.some((t) => t.notes) && (
        <div className="mt-1 space-y-0.5">
          {types.filter((t) => t.notes).map((t) => (
            <p key={t.type} className="text-xs text-zinc-500">
              <span className="font-medium">{t.type}:</span> {t.notes}
            </p>
          ))}
        </div>
      )}
    </div>
  )
}

function RuleList({ title, rules }: { title: string; rules: string[] }) {
  if (!rules.length) return null
  return (
    <div>
      <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-zinc-500">{title}</p>
      <ul className="space-y-0.5 text-xs text-zinc-700 dark:text-zinc-300">
        {rules.map((r, i) => (
          <li key={i} className="flex gap-1.5">
            <span className="mt-0.5 shrink-0 text-zinc-400">·</span>
            <span>{r}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

// ─── detail panel ───────────────────────────────────────────────────────────

function SkillDetailPanel({ skill }: { skill: SkillSummary }) {
  const [detail, setDetail] = useState<SkillDetail | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    setDetail(null)
    setLoading(true)
    api.getSkill(skill.key)
      .then(setDetail)
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [skill.key])

  return (
    <div className="space-y-5 text-sm">
      {/* Header */}
      <div>
        <div className="flex items-start justify-between gap-3">
          <div>
            <Heading>{skill.name}</Heading>
            <p className="text-xs text-zinc-500">{skill.publisher}</p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {skill.open_access && <Badge color="emerald">Open Access</Badge>}
            {skill.impact_factor != null && <Badge color="blue">IF {skill.impact_factor}</Badge>}
          </div>
        </div>
        <div className="mt-2 flex flex-wrap gap-1">
          {skill.disciplines.map((d) => (
            <Badge key={d} color="zinc">{d.replace(/_/g, ' ')}</Badge>
          ))}
        </div>
        {skill.url && (
          <a
            href={skill.url}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-1 inline-block text-xs text-blue-600 hover:underline dark:text-blue-400"
          >
            Author guidelines ↗
          </a>
        )}
      </div>

      {/* Scope */}
      {skill.scope && (
        <div>
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-zinc-500">Scope</p>
          <p className="text-xs leading-relaxed text-zinc-600 dark:text-zinc-400">{skill.scope}</p>
          {skill.scope_keywords.length > 0 && (
            <div className="mt-1.5 flex flex-wrap gap-1">
              {skill.scope_keywords.map((kw) => (
                <span key={kw} className="rounded bg-zinc-100 px-1.5 py-0.5 text-xs text-zinc-500 dark:bg-zinc-800">
                  {kw}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Article types */}
      <div>
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
          Article types &amp; limits
          <span className="ml-1 font-normal normal-case text-amber-600">(⚠ page limits require manual PDF check)</span>
        </p>
        <ArticleTypeTable types={skill.article_types} />
      </div>

      {/* Required sections */}
      {skill.required_sections.length > 0 && (
        <div>
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-zinc-500">Required sections</p>
          <div className="flex flex-wrap gap-1">
            {skill.required_sections.map((s) => (
              <span key={s} className="rounded bg-zinc-100 px-2 py-0.5 text-xs dark:bg-zinc-800">{s}</span>
            ))}
          </div>
        </div>
      )}

      {/* Rules (from detail) */}
      {loading && <p className="text-xs text-zinc-400">Loading rules…</p>}
      {detail && (
        <div className="space-y-4 border-t border-zinc-200 pt-4 dark:border-zinc-700">
          <RuleList title="Structure rules" rules={detail.structure_rules} />
          <RuleList title="Content rules" rules={detail.content_rules} />
          <RuleList title="Compliance rules" rules={detail.compliance_rules} />
          <RuleList title="Language rules" rules={detail.language_rules} />
          <RuleList title="Required declarations" rules={detail.declarations} />
          {(detail.reference_style || detail.reference_format) && (
            <div>
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-zinc-500">References</p>
              <p className="text-xs text-zinc-600 dark:text-zinc-400">
                Style: <span className="font-medium">{detail.reference_style || '—'}</span>
                {detail.reference_format && ` · Format: ${detail.reference_format}`}
              </p>
            </div>
          )}
          {detail.submission_url && (
            <p className="text-xs">
              <span className="font-medium text-zinc-500">Submission:</span>{' '}
              <a href={detail.submission_url} target="_blank" rel="noopener noreferrer"
                 className="text-blue-600 hover:underline dark:text-blue-400">
                {detail.submission_url} ↗
              </a>
            </p>
          )}
          {detail.figures_notes && (
            <p className="text-xs text-zinc-500">
              <span className="font-medium">Figures note:</span> {detail.figures_notes}
            </p>
          )}
        </div>
      )}
    </div>
  )
}

// ─── main page ──────────────────────────────────────────────────────────────

const YAML_TEMPLATE = `journal:
  name: "My Journal"
  abbreviation: "MyJ"
  publisher: "My Publisher"
  url: "https://example.com/for-authors"
  issn: ""
  impact_factor: null
  open_access: true
  discipline: ["my_field"]
  last_verified: "2025-01-01"

scope:
  description: >
    Describe the journal scope here.
  keywords:
    - "keyword1"
    - "keyword2"

article_types:
  - type: "Article"
    word_limit: 8000
    word_limit_scope: "main text"
    abstract_limit: 250
    abstract_type: "structured"
    figures_max: 10
    tables_max: 5
    references_max: 60
    pages_max: null
    notes: ""

format:
  reference_style: "numbered"
  reference_format: "Vancouver"
  keywords_required: true
  keywords_count: 5

sections:
  required: ["Abstract", "Introduction", "Methods", "Results", "Discussion"]
  optional: ["Conclusion", "Supplementary"]
  order: ["Abstract", "Introduction", "Methods", "Results", "Discussion"]

checklist:
  declarations_required:
    - "Conflict of interest statement"
    - "Data availability statement"
  ethics_statement: true
  data_availability: true

agents:
  structure_rules:
    - "Abstract must not exceed 250 words"
  content_rules:
    - "Methods must be reproducible"
  compliance_rules:
    - "Conflict of interest required"
  language_rules:
    - "Write in clear, concise English"
`

export default function SkillsPage() {
  const { t } = useI18n()
  const [skills, setSkills] = useState<SkillSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [query, setQuery] = useState('')
  const [activeTags, setActiveTags] = useState<Set<string>>(new Set())
  const [tagsExpanded, setTagsExpanded] = useState(false)
  const [selected, setSelected] = useState<SkillSummary | null>(null)
  const TAG_LIMIT = 8
  const [rightTab, setRightTab] = useState<'detail' | 'create'>('detail')
  const [editorMode, setEditorMode] = useState<'visual' | 'yaml'>('visual')
  const [newKey, setNewKey] = useState('')
  const [newYaml, setNewYaml] = useState(YAML_TEMPLATE)
  const [visualForm, setVisualForm] = useState<VisualForm>({ ...BLANK_FORM })
  const [saving, setSaving] = useState(false)
  const [saveMsg, setSaveMsg] = useState<string | null>(null)

  function loadSkills() {
    return api.listSkills()
      .then((r) => { setSkills(r.skills); if (!selected && r.skills.length) setSelected(r.skills[0]) })
      .catch(() => {})
      .finally(() => setLoading(false))
  }

  useEffect(() => { loadSkills() }, [])

  async function handleCreate() {
    if (!newKey.trim()) { setSaveMsg('Key is required.'); return }
    setSaving(true)
    setSaveMsg(null)
    const yaml = editorMode === 'visual' ? formToYaml(visualForm, newKey.trim()) : newYaml
    try {
      const r = await api.createSkill(newKey.trim(), yaml)
      setSaveMsg(`${t('common.saved')} ${r.skill.name}`)
      await loadSkills()
      setSelected(r.skill)
      setRightTab('detail')
    } catch (e) {
      setSaveMsg(String(e))
    } finally {
      setSaving(false)
    }
  }

  function startEdit(s: SkillSummary) {
    setNewKey(s.key)
    setNewYaml(YAML_TEMPLATE)
    setEditorMode('yaml')
    setRightTab('create')
    setSaveMsg(null)
    api.getSkill(s.key).then((d) => {
      const lines: string[] = [
        `journal:`,
        `  name: "${d.name}"`,
        `  publisher: "${d.publisher}"`,
        `  url: "${d.url}"`,
        `  impact_factor: ${d.impact_factor ?? 'null'}`,
        `  open_access: ${d.open_access}`,
        `  discipline: [${d.disciplines.map(x => `"${x}"`).join(', ')}]`,
        ``,
        `scope:`,
        `  description: >`,
        `    ${d.scope}`,
        `  keywords: [${d.scope_keywords.map(x => `"${x}"`).join(', ')}]`,
      ]
      setNewYaml(lines.join('\n'))
    }).catch(() => {})
  }

  // All discipline tags, deduplicated and sorted
  const allTags = useMemo(() => {
    const tags = new Set<string>()
    for (const s of skills) for (const d of s.disciplines) tags.add(d)
    return Array.from(tags).sort()
  }, [skills])

  // Filtered skills
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return skills.filter((s) => {
      const matchesTag =
        activeTags.size === 0 || s.disciplines.some((d) => activeTags.has(d))
      if (!matchesTag) return false
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

  function toggleTag(tag: string) {
    setActiveTags((prev) => {
      const next = new Set(prev)
      next.has(tag) ? next.delete(tag) : next.add(tag)
      return next
    })
  }

  return (
    <div className="flex h-[calc(100vh-4rem)] gap-0 overflow-hidden">
      {/* ── Left panel: filter + list ── */}
      <div className="flex w-72 shrink-0 flex-col border-r border-zinc-200 dark:border-zinc-700">
        {/* Search */}
        <div className="border-b border-zinc-200 p-3 dark:border-zinc-700">
          <Input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t('skills.search')}
          />
        </div>

        {/* Discipline tags — collapsible, max-h caps height so list is never squeezed */}
        <div className="shrink-0 border-b border-zinc-200 p-3 dark:border-zinc-700">
          <div className="mb-1.5 flex items-center justify-between">
            <span className="text-xs font-medium text-zinc-500">{t('skills.disciplines')}</span>
            <div className="flex items-center gap-2">
              {activeTags.size > 0 && (
                <button type="button" onClick={() => setActiveTags(new Set())}
                  className="text-xs text-blue-500 hover:underline">{t('skills.clear')}</button>
              )}
              {allTags.length > TAG_LIMIT && (
                <button type="button" onClick={() => setTagsExpanded(v => !v)}
                  className="text-xs text-zinc-400 hover:text-zinc-600">
                  {tagsExpanded ? '▲ less' : `+${allTags.length - TAG_LIMIT} more`}
                </button>
              )}
            </div>
          </div>
          <div className={`flex flex-wrap gap-1 overflow-y-auto ${tagsExpanded ? 'max-h-32' : ''}`}>
            {(tagsExpanded ? allTags : allTags.slice(0, TAG_LIMIT)).map((tag) => (
              <DisciplineBadge
                key={tag}
                tag={tag}
                active={activeTags.has(tag)}
                onClick={() => toggleTag(tag)}
              />
            ))}
          </div>
        </div>

        {/* Skill list */}
        <div className="flex-1 overflow-y-auto">
          {loading && (
            <p className="p-4 text-xs text-zinc-400">{t('common.loading')}</p>
          )}
          {!loading && filtered.length === 0 && (
            <p className="p-4 text-xs text-zinc-400">{t('skills.no_match')}</p>
          )}
          {filtered.map((s) => (
            <button
              key={s.key}
              type="button"
              onClick={() => { setSelected(s); setRightTab('detail') }}
              className={`w-full border-b border-zinc-100 px-3 py-2.5 text-left transition dark:border-zinc-800 ${
                selected?.key === s.key
                  ? 'bg-blue-50 dark:bg-blue-900/20'
                  : 'hover:bg-zinc-50 dark:hover:bg-zinc-800/50'
              }`}
            >
              <div className="flex items-center justify-between gap-1">
                <span className="truncate text-sm font-medium">{s.name}</span>
                {s.impact_factor != null && (
                  <span className="shrink-0 text-xs text-zinc-400">IF {s.impact_factor}</span>
                )}
              </div>
              <p className="truncate text-xs text-zinc-400">{s.publisher}</p>
              <div className="mt-1 flex flex-wrap gap-0.5">
                {s.disciplines.slice(0, 3).map((d) => (
                  <span key={d} className="rounded-full bg-zinc-100 px-1.5 py-px text-[10px] text-zinc-500 dark:bg-zinc-800">
                    {d.replace(/_/g, ' ')}
                  </span>
                ))}
                {s.disciplines.length > 3 && (
                  <span className="text-[10px] text-zinc-400">+{s.disciplines.length - 3}</span>
                )}
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* ── Right panel: detail or create ── */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Tab bar */}
        <div className="flex border-b border-zinc-200 dark:border-zinc-700">
          <button
            type="button"
            onClick={() => setRightTab('detail')}
            className={`px-4 py-2 text-sm font-medium transition ${
              rightTab === 'detail'
                ? 'border-b-2 border-blue-600 text-blue-600'
                : 'text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300'
            }`}
          >
            {t('skills.preview_tab')}
          </button>
          <button
            type="button"
            onClick={() => { setRightTab('create'); setNewKey(''); setVisualForm({ ...BLANK_FORM }); setNewYaml(YAML_TEMPLATE); setSaveMsg(null) }}
            className={`px-4 py-2 text-sm font-medium transition ${
              rightTab === 'create'
                ? 'border-b-2 border-blue-600 text-blue-600'
                : 'text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300'
            }`}
          >
            {t('skills.create_tab')}
          </button>
        </div>

        {rightTab === 'detail' ? (
          <div className="flex-1 overflow-y-auto p-6">
            {selected ? (
              <div className="space-y-4">
                <div className="flex justify-end">
                  <Button onClick={() => startEdit(selected)}>
                    {t('skills.edit_label')}
                  </Button>
                </div>
                <SkillDetailPanel key={selected.key} skill={selected} />
              </div>
            ) : (
              <p className="text-sm text-zinc-400">Select a journal to preview.</p>
            )}
          </div>
        ) : (
          <div className="flex-1 overflow-y-auto p-6 space-y-4">
            <Subheading>{t('skills.create_title')}</Subheading>
            <p className="text-xs text-zinc-500">
              {t('skills.create_hint')}{' '}
              <code className="rounded bg-zinc-100 px-1 dark:bg-zinc-800">skills/journals/{newKey || 'key'}.yaml</code>
            </p>
            <div>
              <label className="mb-1 block text-xs font-medium text-zinc-600 dark:text-zinc-400">
                {t('skills.key_label')}
              </label>
              <Input
                type="text"
                value={newKey}
                onChange={(e) => setNewKey(e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, '_'))}
                placeholder={t('skills.key_placeholder')}
              />
            </div>

            {/* Visual | YAML tabs */}
            <div className="flex gap-1 border-b border-zinc-200 dark:border-zinc-700">
              {(['visual', 'yaml'] as const).map((mode) => (
                <button key={mode} type="button" onClick={() => setEditorMode(mode)}
                  className={`px-3 py-1 text-xs font-medium ${
                    editorMode === mode ? 'border-b-2 border-blue-600 text-blue-600' : 'text-zinc-500 hover:text-zinc-700'
                  }`}>
                  {mode === 'visual' ? t('skills.visual_tab') : t('skills.yaml_tab')}
                </button>
              ))}
            </div>

            {editorMode === 'visual' ? (
              <VisualEditor form={visualForm} onChange={setVisualForm} />
            ) : (
              <Textarea
                value={newYaml}
                onChange={(e) => setNewYaml(e.target.value)}
                rows={28}
              />
            )}

            <div className="flex items-center gap-3">
              <Button onClick={handleCreate} disabled={saving}>
                {saving ? t('skills.saving') : t('skills.save')}
              </Button>
              {saveMsg && (
                <span className={`text-sm ${saveMsg.startsWith(t('common.saved').charAt(0)) ? 'text-emerald-600' : 'text-red-500'}`}>
                  {saveMsg}
                </span>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
