/**
 * Coerces an unknown payload value into text that is safe to render.
 *
 * Runtime and scheduler payloads are loosely typed: a field documented as a
 * message or summary occasionally arrives as a structured object. A bare
 * `String(value)` turns that into the literal `[object Object]`, which is what
 * leaked into the scheduler run views. This helper prefers a real text field
 * when one exists and otherwise falls back to readable JSON.
 */
const TEXT_KEYS = ['text', 'message', 'summary', 'content', 'label', 'title', 'detail'] as const

/** Bounds recursion so a self-referencing payload cannot loop forever. */
const MAX_DEPTH = 5

/** The JSON fallback is a label, not a payload dump. */
const MAX_JSON_LENGTH = 2000

export function displayText(value: unknown): string {
  return toText(value, 0)
}

/** Same as {@link displayText} but keeps a caller-provided fallback. */
export function displayTextOr(value: unknown, fallback: string): string {
  return displayText(value) || fallback
}

function toText(value: unknown, depth: number): string {
  if (value == null) return ''
  switch (typeof value) {
    case 'string':
      return value.trim()
    case 'number':
    case 'boolean':
    case 'bigint':
      return String(value)
    case 'object':
      break
    default:
      // Symbols and functions have no meaningful text form.
      return ''
  }
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? '' : value.toISOString()
  if (depth >= MAX_DEPTH) return ''
  if (Array.isArray(value)) return joinParts(value.map(item => toText(item, depth + 1)))

  const record = value as Record<string, unknown>
  const extracted = joinParts(TEXT_KEYS.map(key => toText(record[key], depth + 1)))
  if (extracted) return extracted
  // A typed content part with no text (screenshot, file, artifact) has nothing
  // to show and may carry megabytes of base64, so never serialize it.
  if (typeof record.type === 'string') return ''
  return truncateJson(safeJson(value))
}

/** Joins non-empty fragments, dropping repeats of the fragment just added. */
function joinParts(values: string[]): string {
  const parts: string[] = []
  for (const value of values) {
    if (value && parts[parts.length - 1] !== value) parts.push(value)
  }
  return parts.join(' ').trim()
}

function safeJson(value: unknown): string {
  try {
    const serialized = JSON.stringify(value, null, 2)
    // Symbols, functions and cyclic structures all serialize to undefined.
    return typeof serialized === 'string' ? serialized : ''
  } catch {
    return ''
  }
}

function truncateJson(value: string): string {
  return value.length > MAX_JSON_LENGTH ? `${value.slice(0, MAX_JSON_LENGTH)}…` : value
}
