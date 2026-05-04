'use client'

// i18n: strings live in src/locales/{en,zh}.json.
// Usage:  const { t, lang, setLang } = useI18n()
// Missing keys fall back to the key itself.

import {
  createContext,
  createElement,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import enJson from '@/locales/en.json'
import zhJson from '@/locales/zh.json'

export type Lang = 'en' | 'zh'

const MESSAGES: Record<Lang, Record<string, string>> = {
  en: enJson as Record<string, string>,
  zh: { ...enJson, ...zhJson } as Record<string, string>,
}

type I18nValue = {
  lang: Lang
  setLang: (l: Lang) => void
  t: (key: string, fallback?: string) => string
}

const I18nContext = createContext<I18nValue | null>(null)

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>('en')

  useEffect(() => {
    const saved = (typeof window !== 'undefined' &&
      (localStorage.getItem('paper-agent.lang') as Lang | null)) || null
    if (saved === 'en' || saved === 'zh') setLangState(saved)
  }, [])

  const setLang = useCallback((l: Lang) => {
    setLangState(l)
    if (typeof window !== 'undefined') localStorage.setItem('paper-agent.lang', l)
  }, [])

  const t = useCallback(
    (key: string, fallback?: string) => MESSAGES[lang][key] ?? fallback ?? key,
    [lang],
  )

  const value = useMemo<I18nValue>(() => ({ lang, setLang, t }), [lang, setLang, t])
  return createElement(I18nContext.Provider, { value }, children)
}

export function useI18n(): I18nValue {
  const v = useContext(I18nContext)
  if (!v) {
    return { lang: 'en', setLang: () => {}, t: (k, f) => MESSAGES.en[k] ?? f ?? k }
  }
  return v
}
