import { isSchedulerRequest } from '@/stores/runtime/eventUtils'
import { scopeFromEventPayload } from '@/stores/runtime/scopes'
import { schedulerRunNoticeView } from '@/stores/runtime/viewMappers'
import { useRuntimeStore } from '@/stores/runtime'
import type { FactoryFrontendEvent } from '@/types/protocol'
import {
  publishTaskNotification,
  type TaskNotificationStatus,
  type TaskTerminalNotification,
} from './taskNotifications'

export interface TaskNotificationEventContext {
  conversationTitle: string | null
}
const TERMINAL_SCHEDULER_EVENTS = new Set([
  'scheduler_run_completed',
  'scheduler_run_failed',
  'scheduler_run_skipped',
  'scheduler_run_cancelled',
])

export function captureTaskNotificationEventContext(
  event: FactoryFrontendEvent,
): TaskNotificationEventContext {
  const runtimeStore = useRuntimeStore()
  const sessionId = conversationSessionId(event)
  const session = [...runtimeStore.sessions, ...runtimeStore.agentSessions].find((item: any) => (
    String(item?.session_id || '').trim() === sessionId
  )) as any
  return {
    conversationTitle: text(session?.title || session?.name),
  }
}

export function publishTaskNotificationsForEvent(
  event: FactoryFrontendEvent,
  _context: TaskNotificationEventContext,
): void {
  if (TERMINAL_SCHEDULER_EVENTS.has(event.event_type)) {
    const notification = schedulerNotification(event)
    if (notification) publishTaskNotification(notification)
    return
  }
  const notification = conversationNotification(event, _context)
  if (notification) publishTaskNotification(notification)
}

function conversationNotification(
  event: FactoryFrontendEvent,
  context: TaskNotificationEventContext,
): TaskTerminalNotification | null {
  const status = runTerminalStatus(event)
  if (!status || isSchedulerRequest(event.request_id)) return null
  const finishStatus = text(event.payload?.finish_status || event.payload?.status)
  if (finishStatus === 'waiting_for_workers') return null

  const mode = 'agent_package' as const
  const sessionId = conversationSessionId(event)
  const packageId = text(event.payload?.package_id || event.payload?.agent_session?.package_id)
  return {
    key: `conversation:${event.request_id || event.event_id}:${status}`,
    category: 'conversation',
    status,
    subject: text(
      event.payload?.source_task_name
      || event.payload?.agent_name
      || event.payload?.agent_session?.title
      || event.payload?.session_title
      || context.conversationTitle,
    ),
    body: eventSummary(event),
    target: {
      kind: 'conversation',
      mode,
      sessionId,
      packageId,
      conversationScope: scopeFromEventPayload(event),
    },
  }
}

function schedulerNotification(event: FactoryFrontendEvent): TaskTerminalNotification | null {
  const notice = schedulerRunNoticeView(event)
  if (!notice) return null
  const status = notificationStatus(notice.status)
  if (!status) return null
  return {
    key: `scheduler:${notice.id}:${status}`,
    category: 'scheduler',
    status,
    subject: notice.title,
    body: notice.summary,
    target: { kind: 'scheduler' },
  }
}

function runTerminalStatus(event: FactoryFrontendEvent): TaskNotificationStatus | null {
  if (event.event_type === 'run_failed') return 'failed'
  if (event.event_type === 'run_cancelled') return 'cancelled'
  if (event.event_type !== 'run_completed') return null
  const reported = text(event.payload?.finish_status || event.payload?.status)
  return reported === 'stopped' || reported === 'cancelled' ? 'cancelled' : 'completed'
}

function notificationStatus(value: string): TaskNotificationStatus | null {
  if (value === 'completed') return 'completed'
  if (value === 'failed') return 'failed'
  if (value === 'cancelled') return 'cancelled'
  if (value === 'skipped') return 'skipped'
  return null
}

function conversationSessionId(event: FactoryFrontendEvent): string | null {
  return text(
    event.payload?.agent_session?.session_id
    || event.payload?.session_id
    || event.session_id,
  )
}

function eventSummary(event: FactoryFrontendEvent): string | null {
  if (event.event_type === 'run_cancelled') return null
  return text(
    event.payload?.output_summary
    || event.payload?.result_summary
    || event.payload?.summary
    || event.payload?.error_summary
    || event.payload?.error_message
    || event.payload?.error
    || event.message,
  )
}

function text(value: unknown): string | null {
  const normalized = structuredText(value)
  return normalized || null
}

function structuredText(value: unknown): string {
  if (value == null) return ''
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return String(value).trim()
  }
  if (Array.isArray(value)) {
    return value.map(structuredText).filter(Boolean).join(' · ')
  }
  if (typeof value !== 'object') return ''
  const record = value as Record<string, unknown>
  for (const key of ['user_message', 'message', 'summary', 'reason', 'error_message', 'code']) {
    const candidate = structuredText(record[key])
    if (candidate) return candidate
  }
  return ''
}
