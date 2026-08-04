/*
 * Pure formatting helpers. No component state — safe to unit test directly.
 */

/** Human-readable byte size, e.g. 1536 -> "1.5 KB". */
export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null || !Number.isFinite(bytes) || bytes < 0) return '—'
  if (bytes === 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  const exponent = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  const value = bytes / Math.pow(1024, exponent)
  const rounded = value >= 100 || exponent === 0 ? Math.round(value) : Math.round(value * 10) / 10
  return `${rounded} ${units[exponent]}`
}

/** Compact count, e.g. 1200 -> "1.2k". */
export function formatCount(count: number | null | undefined): string {
  if (count == null || !Number.isFinite(count) || count < 0) return '0'
  if (count < 1000) return String(count)
  if (count < 1_000_000) return `${Math.round(count / 100) / 10}k`
  return `${Math.round(count / 100_000) / 10}M`
}

/** Localized date, tolerant of empty/invalid ISO strings. */
export function formatDate(iso: string | null | undefined, locale: string): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat(locale === 'zh' ? 'zh-CN' : 'en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  }).format(date)
}

/** Shorten a SHA-256 for compact display. */
export function shortHash(hash: string | null | undefined): string {
  if (!hash) return '—'
  return hash.length > 16 ? `${hash.slice(0, 8)}…${hash.slice(-6)}` : hash
}
