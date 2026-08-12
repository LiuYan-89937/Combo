const FIRST_RUN_GUIDE_STORAGE_KEY = 'combo.first-run-guide.v2'
const COMPLETED_VALUE = 'completed'

export function hasCompletedFirstRunGuide(): boolean {
  if (typeof window === 'undefined') return true
  return window.localStorage.getItem(FIRST_RUN_GUIDE_STORAGE_KEY) === COMPLETED_VALUE
}

export function completeFirstRunGuide(): void {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(FIRST_RUN_GUIDE_STORAGE_KEY, COMPLETED_VALUE)
}
