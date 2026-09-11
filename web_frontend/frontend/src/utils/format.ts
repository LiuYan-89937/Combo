import type { Locale } from '@/i18n'

/**
 * 时间与体积格式化的唯一实现处。
 *
 * 各组件只负责决定「展示哪一种」（相对时间 / 时刻 / 日期 / 体积），
 * 解析与格式化逻辑都收敛在这里，不再各自实现一份。
 */

/** 解析时间戳；空值或无法解析时返回 null。 */
export function parseDate(value: unknown): Date | null {
  if (value == null || value === '') return null
  const date = value instanceof Date ? value : new Date(String(value))
  return Number.isFinite(date.getTime()) ? date : null
}

/** 是否与 now 为同一天。 */
export function isToday(date: Date, now: Date = new Date()): boolean {
  return date.toDateString() === now.toDateString()
}

/** 相对当前时间的分钟数，如「3 分钟前」。 */
export function formatRelativeMinutes(date: Date, locale?: Locale): string {
  const minutes = Math.floor((Date.now() - date.getTime()) / 60_000)
  return new Intl.RelativeTimeFormat(locale, { numeric: 'auto' }).format(-minutes, 'minute')
}

/** 时刻，如 14:05。 */
export function formatClockTime(date: Date, locale?: Locale): string {
  return new Intl.DateTimeFormat(locale, { hour: '2-digit', minute: '2-digit' }).format(date)
}

/** 短日期加时刻，如 9月11日 14:05。 */
export function formatShortDateTime(date: Date, locale?: Locale): string {
  return new Intl.DateTimeFormat(locale, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

/** 字节数 → 可读体积（B/KB/MB/GB/TB）。 */
export function formatBytes(bytes: number): string {
  const value = Math.max(0, Number(bytes) || 0)
  if (value < 1024) return `${value} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let amount = value / 1024
  let index = 0
  while (amount >= 1024 && index < units.length - 1) {
    amount /= 1024
    index += 1
  }
  return `${amount.toFixed(1)} ${units[index]}`
}
