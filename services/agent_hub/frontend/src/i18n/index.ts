/*
 * Minimal reactive i18n. No external dependency: a Pinia store holds the
 * active locale, and `t(path, vars)` walks the message catalog. Locale is
 * persisted to localStorage and reflected on <html lang>.
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { catalogs, type Locale } from './messages'

const STORAGE_KEY = 'faf-locale'
const SUPPORTED: Locale[] = ['zh', 'en']

function detectLocale(): Locale {
  try {
    const stored = localStorage.getItem(STORAGE_KEY) as Locale | null
    if (stored && SUPPORTED.includes(stored)) return stored
  } catch {
    /* localStorage may be unavailable */
  }
  const nav = typeof navigator !== 'undefined' ? navigator.language.toLowerCase() : 'zh'
  return nav.startsWith('zh') ? 'zh' : 'en'
}

function resolve(catalog: unknown, path: string): string | undefined {
  const parts = path.split('.')
  let node: unknown = catalog
  for (const part of parts) {
    if (node && typeof node === 'object' && part in (node as Record<string, unknown>)) {
      node = (node as Record<string, unknown>)[part]
    } else {
      return undefined
    }
  }
  return typeof node === 'string' ? node : undefined
}

function interpolate(template: string, vars?: Record<string, string | number>): string {
  if (!vars) return template
  return template.replace(/\{(\w+)\}/g, (match, key: string) =>
    key in vars ? String(vars[key]) : match,
  )
}

export const useI18nStore = defineStore('i18n', () => {
  const locale = ref<Locale>(detectLocale())

  function applyToDocument() {
    if (typeof document !== 'undefined') {
      document.documentElement.setAttribute('lang', locale.value === 'zh' ? 'zh-CN' : 'en')
    }
  }
  applyToDocument()

  function setLocale(next: Locale) {
    if (!SUPPORTED.includes(next)) return
    locale.value = next
    try {
      localStorage.setItem(STORAGE_KEY, next)
    } catch {
      /* ignore */
    }
    applyToDocument()
  }

  function toggleLocale() {
    setLocale(locale.value === 'zh' ? 'en' : 'zh')
  }

  const t = (path: string, vars?: Record<string, string | number>): string => {
    const active = resolve(catalogs[locale.value], path)
    const fallback = active ?? resolve(catalogs.zh, path)
    return interpolate(fallback ?? path, vars)
  }

  const localeTag = computed(() => (locale.value === 'zh' ? 'zh-CN' : 'en-US'))

  return { locale, localeTag, setLocale, toggleLocale, t }
})

/** Convenience composable so components read like `const { t } = useI18n()`. */
export function useI18n() {
  const store = useI18nStore()
  return {
    t: store.t,
    locale: computed(() => store.locale),
    localeTag: computed(() => store.localeTag),
    setLocale: store.setLocale,
    toggleLocale: store.toggleLocale,
  }
}

export type { Locale }
