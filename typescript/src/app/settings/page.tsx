'use client'

import { Heading, Subheading } from '@/components/heading'
import { Text, Strong } from '@/components/text'
import { Badge } from '@/components/badge'
import { Listbox, ListboxLabel, ListboxOption } from '@/components/listbox'
import { Field, Label } from '@/components/fieldset'
import { Input } from '@/components/input'
import { Button } from '@/components/button'
import { useEffect, useState } from 'react'
import { api } from '@/lib/api'
import { useI18n, type Lang } from '@/lib/i18n'

type ConfigState = {
  api_key_masked: string
  api_key_set: boolean
  base_url: string
  fast_model: string
  smart_model: string
  deep_model: string
}

export default function SettingsPage() {
  const { t, lang, setLang } = useI18n()
  const [models, setModels] = useState<string[]>([])
  const [config, setConfig] = useState<ConfigState | null>(null)
  // Form state -- only fields the user actually edits.
  const [baseUrl, setBaseUrl] = useState('')
  const [apiKey, setApiKey] = useState('')           // blank = leave unchanged
  const [fastModel, setFastModel] = useState('')
  const [smartModel, setSmartModel] = useState('')
  const [deepModel, setDeepModel] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [info, setInfo] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const [m, c] = await Promise.all([api.listModels(), api.getConfig()])
      setModels(m.models)
      setConfig(c)
      setBaseUrl(c.base_url)
      setFastModel(c.fast_model)
      setSmartModel(c.smart_model)
      setDeepModel(c.deep_model)
      setApiKey('')
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => {
    load()
  }, [])

  async function save() {
    setSaving(true)
    setError(null)
    setInfo(null)
    try {
      const patch: Record<string, string> = {
        base_url: baseUrl,
        fast_model: fastModel,
        smart_model: smartModel,
        deep_model: deepModel,
      }
      if (apiKey.trim()) patch.api_key = apiKey.trim()
      const c = await api.updateConfig(patch)
      setConfig(c)
      setApiKey('') // clear the input so the masked value is shown again
      setInfo(t('common.saved'))
    } catch (e) {
      setError(String(e))
    } finally {
      setSaving(false)
    }
  }

  async function testConnection() {
    setTesting(true)
    setError(null)
    setInfo(null)
    try {
      const r = await api.testConfig()
      if (r.ok) {
        setInfo(t('settings.test_ok').replace('{n}', String(r.model_count ?? 0)))
        // Refresh discovered models so the dropdowns get the new list.
        const m = await api.listModels()
        setModels(m.models)
      } else {
        setError(t('settings.test_fail').replace('{err}', r.error || 'unknown'))
      }
    } catch (e) {
      setError(String(e))
    } finally {
      setTesting(false)
    }
  }

  async function clearKey() {
    setSaving(true)
    setError(null)
    try {
      const c = await api.updateConfig({ api_key: '__clear__' })
      setConfig(c)
      setApiKey('')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-8">
      <Heading>{t('settings.title')}</Heading>

      {/* ============ Language ============ */}
      <section className="space-y-3 rounded-xl border border-zinc-950/10 bg-white p-6 dark:border-white/10 dark:bg-zinc-900">
        <Subheading>{t('settings.lang')}</Subheading>
        <Field>
          <Label className="sr-only">{t('settings.lang')}</Label>
          <Listbox value={lang} onChange={(v) => setLang((v ?? 'en') as Lang)}>
            <ListboxOption value="en"><ListboxLabel>English</ListboxLabel></ListboxOption>
            <ListboxOption value="zh"><ListboxLabel>中文</ListboxLabel></ListboxOption>
          </Listbox>
        </Field>
      </section>

      {/* ============ API endpoint ============ */}
      <section className="space-y-3 rounded-xl border border-zinc-950/10 bg-white p-6 dark:border-white/10 dark:bg-zinc-900">
        <Subheading>{t('settings.endpoint_title')}</Subheading>
        <Text className="text-sm">{t('settings.endpoint_hint')}</Text>

        <Field>
          <Label>{t('settings.base_url')}</Label>
          <Input
            type="url"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.currentTarget.value)}
            placeholder="https://api.example.com/v1/"
          />
        </Field>

        <Field>
          <Label>{t('settings.api_key')}</Label>
          <Input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.currentTarget.value)}
            placeholder={t('settings.api_key_placeholder')}
            autoComplete="new-password"
          />
          <Text className="text-xs text-zinc-500">
            {config?.api_key_set
              ? `${t('settings.api_key_set')} — ${config.api_key_masked}`
              : t('settings.api_key_unset')}
          </Text>
        </Field>
      </section>

      {/* ============ Model tier mapping ============ */}
      <section className="space-y-3 rounded-xl border border-zinc-950/10 bg-white p-6 dark:border-white/10 dark:bg-zinc-900">
        <div className="flex items-center justify-between">
          <Subheading>{t('settings.models_title')}</Subheading>
          <Button onClick={load} disabled={loading}>
            {loading ? t('common.loading') : t('logs.refresh_history')}
          </Button>
        </div>
        <Text className="text-sm">{t('settings.models_hint')}</Text>

        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <ModelPicker
            label={t('settings.fast')}
            value={fastModel}
            onChange={setFastModel}
            options={models}
          />
          <ModelPicker
            label={t('settings.smart')}
            value={smartModel}
            onChange={setSmartModel}
            options={models}
          />
          <ModelPicker
            label={t('settings.deep')}
            value={deepModel}
            onChange={setDeepModel}
            options={models}
          />
        </div>

        <div>
          <Strong>{t('settings.discovered')} ({models.length})</Strong>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {models.length === 0 ? (
              <Text className="text-xs text-zinc-500">
                {t('settings.no_models_hint')}
              </Text>
            ) : (
              models.map((m) => <Badge key={m} color="blue">{m}</Badge>)
            )}
          </div>
        </div>
      </section>

      {/* ============ Action bar ============ */}
      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={save} disabled={saving} color="dark">
          {saving ? t('common.loading') : t('settings.save')}
        </Button>
        <Button onClick={testConnection} disabled={testing} outline>
          {testing ? t('common.loading') : t('settings.test')}
        </Button>
        {config?.api_key_set ? (
          <Button onClick={clearKey} plain>
            {t('settings.clear')}
          </Button>
        ) : null}
        {error ? <Text className="text-sm text-red-600">{error}</Text> : null}
        {info ? <Text className="text-sm text-emerald-600">{info}</Text> : null}
      </div>
    </div>
  )
}

function ModelPicker({
  label,
  value,
  onChange,
  options,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  options: string[]
}) {
  // If the saved value isn't in `options` (e.g. discovery list is stale), keep
  // it as a sticky option so the user doesn't lose their existing pick.
  const opts = value && !options.includes(value) ? [value, ...options] : options
  return (
    <Field>
      <Label>{label}</Label>
      <Listbox
        value={value || null}
        onChange={(v) => onChange(v ?? '')}
        placeholder="—"
      >
        {opts.map((m) => (
          <ListboxOption key={m} value={m}>
            <ListboxLabel className="font-mono text-xs">{m}</ListboxLabel>
          </ListboxOption>
        ))}
      </Listbox>
    </Field>
  )
}
