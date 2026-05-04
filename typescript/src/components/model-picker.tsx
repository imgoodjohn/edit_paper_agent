'use client'

import { useEffect, useState } from 'react'
import { api } from '@/lib/api'
import { useI18n } from '@/lib/i18n'
import { Listbox, ListboxOption, ListboxLabel } from '@/components/listbox'

type Props = {
  value: string
  onChange: (v: string) => void
  label?: string
  width?: string
}

export function ModelPicker({ value, onChange, label, width }: Props) {
  const { t } = useI18n()
  const [models, setModels] = useState<string[]>([])
  const [loading, setLoading] = useState(false)

  async function load() {
    setLoading(true)
    try {
      const r = await api.listModels()
      setModels(r.models)
    } catch {
      setModels([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const options = models.length > 0 ? models : []

  return (
    <div className="flex items-center gap-1.5">
      <span className="shrink-0 text-xs text-zinc-500 whitespace-nowrap">
        {label ?? t('model.label')}:
      </span>
      <Listbox<string>
        value={value || ''}
        onChange={onChange}
        disabled={loading}
        className={width ?? 'min-w-[200px]'}
        placeholder={loading ? t('common.loading') : t('model.custom_placeholder')}
      >
        <ListboxOption value="">
          <ListboxLabel className="text-zinc-400">{loading ? t('common.loading') : t('model.custom_placeholder')}</ListboxLabel>
        </ListboxOption>
        {options.map((m) => (
          <ListboxOption key={m} value={m}>
            <ListboxLabel>{m}</ListboxLabel>
          </ListboxOption>
        ))}
      </Listbox>
    </div>
  )
}
