'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { api } from '@/lib/api'
import { useI18n } from '@/lib/i18n'
import { JournalPicker } from '@/components/journal-picker'

export default function UploadPage() {
  const { t } = useI18n()
  const router = useRouter()
  const [journal, setJournal] = useState<string>('')
  const [autoPick, setAutoPick] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit() {
    if (!file) { setError(t('upload.file') + ' required.'); return }
    setBusy(true)
    setError(null)
    try {
      const r = await api.upload(file, autoPick ? '' : journal)
      router.push(`/sessions/${r.session_id}`)
    } catch (e) {
      setError(String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto max-w-2xl space-y-8">
      <div>
        <h1 className="text-2xl font-semibold">{t('upload.title')}</h1>
        <p className="mt-2 text-sm text-zinc-500">{t('upload.desc')}</p>
      </div>

      <div className="space-y-5 rounded-xl border border-zinc-200 bg-white p-6 shadow-sm dark:border-zinc-700 dark:bg-zinc-900">
        {/* File picker */}
        <div>
          <label className="mb-1 block text-sm font-medium">{t('upload.file')}</label>
          <input
            type="file"
            accept=".tex,.docx"
            onChange={(e) => setFile(e.currentTarget.files?.[0] ?? null)}
            className="block w-full rounded border border-zinc-300 bg-white px-2.5 py-1.5 text-sm dark:border-zinc-600 dark:bg-zinc-800"
          />
          {file && (
            <p className="mt-1 text-xs text-zinc-400">{file.name} ({Math.round(file.size / 1024)} KB)</p>
          )}
        </div>

        {/* Auto-pick toggle */}
        <div className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-700">
          <label className="flex cursor-pointer items-center justify-between gap-4">
            <div>
              <span className="text-sm font-medium">{t('upload.auto_pick')}</span>
              <p className="mt-0.5 text-xs text-zinc-500">{t('upload.auto_pick_hint')}</p>
            </div>
            {/* Native toggle pill */}
            <button
              type="button"
              role="switch"
              aria-checked={autoPick}
              onClick={() => setAutoPick(v => !v)}
              className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 focus:outline-none ${
                autoPick ? 'bg-blue-600' : 'bg-zinc-300 dark:bg-zinc-600'
              }`}
            >
              <span
                className={`inline-block h-5 w-5 transform rounded-full bg-white shadow transition duration-200 ${
                  autoPick ? 'translate-x-5' : 'translate-x-0'
                }`}
              />
            </button>
          </label>
        </div>

        {/* Journal picker */}
        {!autoPick && (
          <div>
            <label className="mb-1 block text-sm font-medium">{t('upload.target_journal')}</label>
            <JournalPicker value={journal} onChange={setJournal} disabled={busy} className="w-full" />
          </div>
        )}

        <div className="flex justify-end pt-1">
          <button
            type="button"
            onClick={handleSubmit}
            disabled={busy || !file}
            className="rounded bg-blue-600 px-5 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {busy ? t('upload.uploading') : t('upload.submit')}
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-700 dark:border-red-600/40 dark:bg-red-900/20 dark:text-red-300">
          <strong>{t('common.error')}:</strong> {error}
          <button type="button" onClick={() => setError(null)} className="ml-3 underline">{t('common.dismiss')}</button>
        </div>
      )}
    </div>
  )
}
