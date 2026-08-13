import type { I18nKey } from '@/i18n'
import { toolPresentation } from '@/utils/toolPresentation'

type Translate = (key: I18nKey, params?: Record<string, string | number>) => string

const STATUS_KEYS: Record<string, I18nKey> = {
  queued: 'backgroundTask.description.queued',
  claimed: 'backgroundTask.description.claimed',
  proposed: 'backgroundTask.toolStatus.proposed',
  waiting_approval: 'backgroundTask.toolStatus.waiting_approval',
  running: 'backgroundTask.description.running',
  cancelling: 'backgroundTask.description.cancelling',
  cancelled: 'backgroundTask.description.cancelled',
  completed: 'backgroundTask.description.succeeded',
  succeeded: 'backgroundTask.description.succeeded',
  failed: 'backgroundTask.description.failed',
  rejected: 'backgroundTask.toolStatus.rejected',
  timed_out: 'backgroundTask.toolStatus.timed_out',
}

const SENTENCE_KEYS: Record<string, I18nKey> = {
  'tool execution completed.': 'backgroundTask.toolStatus.completed',
  'tool execution failed.': 'backgroundTask.toolStatus.failed',
  'tool execution cancelled.': 'backgroundTask.toolStatus.cancelled',
}

export function backgroundTaskActivityText(value: unknown, t: Translate): string {
  const summary = String(value || '').trim()
  if (!summary) return ''
  const normalized = summary.toLowerCase().replace(/\s+/g, '_')
  const directKey = STATUS_KEYS[normalized] || SENTENCE_KEYS[summary.toLowerCase()]
  if (directKey) return t(directKey)
  const toolStatus = summary.match(
    /^([a-z][a-z0-9_-]*)\s+(proposed|waiting_approval|running|completed|failed|cancelled|rejected|timed_out)$/i,
  )
  if (!toolStatus) return summary
  const presentation = toolPresentation(toolStatus[1], {})
  const toolLabel = presentation.labelKey ? t(presentation.labelKey as I18nKey) : toolStatus[1]
  return `${toolLabel} · ${t(`backgroundTask.toolStatus.${toolStatus[2].toLowerCase()}` as I18nKey)}`
}
