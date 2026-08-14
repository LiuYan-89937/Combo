import { describe, expect, it, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useI18nStore } from '@/i18n'
import { zh, en } from '@/i18n/messages'

function keys(obj: Record<string, unknown>, prefix = ''): string[] {
  return Object.entries(obj).flatMap(([k, v]) => {
    const path = prefix ? `${prefix}.${k}` : k
    return typeof v === 'object' && v !== null ? keys(v as Record<string, unknown>, path) : [path]
  })
}

describe('message catalogs', () => {
  it('zh and en share the same key structure', () => {
    expect(keys(zh).sort()).toEqual(keys(en).sort())
  })
})

describe('i18n store', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('resolves nested keys and interpolates variables', () => {
    const store = useI18nStore()
    store.setLocale('en')
    expect(store.t('nav.changelog')).toBe('Changelog')
    expect(store.t('home.totalDownloads', { count: 12 })).toBe('12 installer downloads')
  })

  it('falls back to the raw path for an unknown key', () => {
    const store = useI18nStore()
    expect(store.t('does.not.exist')).toBe('does.not.exist')
  })

  it('toggles between locales', () => {
    const store = useI18nStore()
    store.setLocale('zh')
    expect(store.t('nav.login')).toBe('登录')
    store.toggleLocale()
    expect(store.locale).toBe('en')
    expect(store.t('nav.login')).toBe('Sign in')
  })
})
