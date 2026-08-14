/*
 * Theme store. Mirrors the pre-paint inline script in index.html: reads/writes
 * `faf-theme` and toggles the `data-theme` attribute on <html>. When the user
 * has made no explicit choice we follow the OS preference live.
 */
import { ref } from 'vue'
import { defineStore } from 'pinia'

export type Theme = 'light' | 'dark'
const STORAGE_KEY = 'faf-theme'

function systemPrefersDark(): boolean {
  return typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches
}

function storedTheme(): Theme | null {
  try {
    const value = localStorage.getItem(STORAGE_KEY)
    return value === 'light' || value === 'dark' ? value : null
  } catch {
    return null
  }
}

export const useThemeStore = defineStore('theme', () => {
  const explicit = storedTheme()
  const theme = ref<Theme>(explicit ?? (systemPrefersDark() ? 'dark' : 'light'))
  const isExplicit = ref(explicit !== null)

  function apply() {
    if (typeof document !== 'undefined') {
      document.documentElement.setAttribute('data-theme', theme.value)
      document.documentElement.style.colorScheme = theme.value
    }
  }
  apply()

  // Follow the system while the user has not overridden it.
  if (typeof window !== 'undefined' && window.matchMedia) {
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (event) => {
      if (!isExplicit.value) {
        theme.value = event.matches ? 'dark' : 'light'
        apply()
      }
    })
  }

  function setTheme(next: Theme) {
    theme.value = next
    isExplicit.value = true
    try {
      localStorage.setItem(STORAGE_KEY, next)
    } catch {
      /* ignore */
    }
    apply()
  }

  function toggle() {
    setTheme(theme.value === 'dark' ? 'light' : 'dark')
  }

  return { theme, isExplicit, setTheme, toggle }
})
