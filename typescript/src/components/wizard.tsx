'use client'

/**
 * Lightweight wizard / step indicator used at the top of the session page.
 *
 * The component is purely presentational -- the parent computes which step is
 * `current` (1..N) based on session state (`comprehension_confirmed`,
 * `plan_approved`, etc.) and whether each step is `done`.
 */
import clsx from 'clsx'
import { useI18n } from '@/lib/i18n'

export type WizardStep = {
  id: number
  label: string
  done: boolean
}

export function Wizard({
  steps,
  current,
}: {
  steps: WizardStep[]
  current: number
}) {
  const { t } = useI18n()
  return (
    <ol className="flex w-full flex-wrap items-center gap-2">
      {steps.map((s, i) => {
        const isCurrent = s.id === current
        const isDone = s.done
        const isLocked = !isDone && s.id > current
        return (
          <li key={s.id} className="flex flex-1 items-center gap-2 min-w-[140px]">
            <div
              className={clsx(
                'flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold',
                isDone && 'bg-emerald-600 text-white',
                isCurrent && !isDone && 'bg-blue-600 text-white animate-pulse',
                isLocked && 'bg-zinc-200 text-zinc-500 dark:bg-zinc-700 dark:text-zinc-400',
                !isDone && !isCurrent && !isLocked && 'bg-zinc-300 text-zinc-700',
              )}
              aria-current={isCurrent ? 'step' : undefined}
              title={
                isDone
                  ? t('wizard.done')
                  : isCurrent
                    ? t('wizard.current')
                    : t('wizard.locked')
              }
            >
              {isDone ? '✓' : s.id}
            </div>
            <div className="flex flex-col">
              <span className="text-[10px] uppercase tracking-wide text-zinc-500">
                {t('wizard.step')} {s.id} {t('wizard.of')} {steps.length}
              </span>
              <span
                className={clsx(
                  'text-sm font-medium',
                  isCurrent && 'text-blue-700 dark:text-blue-300',
                  isLocked && 'text-zinc-400',
                )}
              >
                {s.label}
              </span>
            </div>
            {i < steps.length - 1 ? (
              <div
                className={clsx(
                  'h-px flex-1',
                  isDone ? 'bg-emerald-600' : 'bg-zinc-200 dark:bg-zinc-700',
                )}
              />
            ) : null}
          </li>
        )
      })}
    </ol>
  )
}
