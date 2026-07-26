import type { CollaborationSessionView, CollaborationTaskView } from '@/api/collaboration'
import { useAgentGroupStore } from '@/stores/agentGroup'
import { useCollaborationStore } from '@/stores/collaboration'
import { isSchedulerRequest } from '@/stores/runtime/eventUtils'
import { scopeFromEventPayload } from '@/stores/runtime/scopes'
import { schedulerRunNoticeView } from '@/stores/runtime/viewMappers'
import type { FactoryFrontendEvent, FactoryMode } from '@/types/protocol'
import {
  publishTaskNotification,
  type TaskNotificationStatus,
  type TaskTerminalNotification,
} from './taskNotifications'

export interface TaskNotificationEventContext {
  previousCollaborationSession: CollaborationSessionView | null
}

const TERMINAL_COLLABORATION_STATUSES = new Set(['completed', 'failed', 'cancelled'])
const TERMINAL_SCHEDULER_EVENTS = new Set([
  'scheduler_run_completed',
  'scheduler_run_failed',
  'scheduler_run_skipped',
  'scheduler_run_cancelled',
])

export function captureTaskNotificationEventContext(
  event: FactoryFrontendEvent,
): TaskNotificationEventContext {
  if (event.event_type !== 'collaboration_session_updated') {
    return { previousCollaborationSession: null }
  }
  const collaborationId = text(event.payload?.collaboration_id)
  if (!collaborationId) return { previousCollaborationSession: null }
  const store = useCollaborationStore()
  const session = store.sessions.find((item) => item.collaboration_id === collaborationId)
    || (store.activeSession?.collaboration_id === collaborationId ? store.activeSession : null)
  return {
    previousCollaborationSession: session ? snapshotCollaborationSession(session) : null,
  }
}

export function publishTaskNotificationsForEvent(
  event: FactoryFrontendEvent,
  context: TaskNotificationEventContext,
): void {
  if (event.payload?.group_id && event.payload?.group_run_id) {
    const notification = groupRunNotification(event)
    if (notification) publishTaskNotification(notification)
    return
  }
  if (TERMINAL_SCHEDULER_EVENTS.has(event.event_type)) {
    const notification = schedulerNotification(event)
    if (notification) publishTaskNotification(notification)
    return
  }
  if (event.event_type === 'collaboration_session_updated') {
    collaborationNotifications(event, context.previousCollaborationSession)
      .forEach(publishTaskNotification)
    return
  }
  const notification = conversationNotification(event)
  if (notification) publishTaskNotification(notification)
}

function conversationNotification(event: FactoryFrontendEvent): TaskTerminalNotification | null {
  const status = runTerminalStatus(event)
  if (!status || isSchedulerRequest(event.request_id)) return null
  const finishStatus = text(event.payload?.finish_status || event.payload?.status)
  if (finishStatus === 'waiting_for_workers') return null

  const collaborationId = collaborationIdFromEvent(event)
  const collaborationTaskId = collaborationTaskIdFromEvent(event)
  if (collaborationTaskId && collaborationId) {
    const collaborationStore = useCollaborationStore()
    const task = findCollaborationTask(collaborationStore.activeSession, collaborationTaskId)
    const agent = task ? collaborationStore.agentById(task.assignee_package_id) : null
    return {
      key: `collaboration-task:${collaborationTaskId}:${status}`,
      category: 'collaboration',
      status,
      subject: agent?.agent_name || text(event.payload?.package_name),
      body: task?.result_summary || eventSummary(event),
      target: {
        kind: 'collaboration',
        collaborationId,
        taskId: collaborationTaskId,
      },
    }
  }

  const mode = normalizedMode(event.mode)
  const sessionId = conversationSessionId(event, mode)
  const packageId = mode === 'agent_package'
    ? text(event.payload?.package_id || event.payload?.agent_session?.package_id)
    : null
  if (collaborationId) {
    return {
      key: `collaboration-reply:${event.request_id || event.event_id}:${status}`,
      category: 'collaboration',
      status,
      subject: text(event.payload?.package_name),
      body: eventSummary(event),
      target: { kind: 'collaboration', collaborationId },
    }
  }

  return {
    key: `conversation:${event.request_id || event.event_id}:${status}`,
    category: 'conversation',
    status,
    subject: text(event.payload?.package_name || event.payload?.agent_session?.package_name),
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

function groupRunNotification(event: FactoryFrontendEvent): TaskTerminalNotification | null {
  const status = runTerminalStatus(event)
  if (!status) return null
  const groupId = text(event.payload?.group_id)
  const groupRunId = text(event.payload?.group_run_id)
  if (!groupId || !groupRunId) return null
  const store = useAgentGroupStore()
  const run = store.activeGroup?.runs.find((item) => item.group_run_id === groupRunId)
  const packageId = text(event.payload?.package_id || run?.speaker_package_id)
  return {
    key: `agent-group-run:${groupRunId}:${status}`,
    category: 'agentGroup',
    status,
    subject: packageId ? store.agentById(packageId)?.agent_name || packageId : null,
    body: eventSummary(event),
    target: { kind: 'agentGroup', groupId },
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

function collaborationNotifications(
  event: FactoryFrontendEvent,
  previous: CollaborationSessionView | null,
): TaskTerminalNotification[] {
  const session = event.payload?.session as CollaborationSessionView | undefined
  if (!session?.collaboration_id || !previous) return []
  const notifications: TaskTerminalNotification[] = []
  const previousTasks = new Map((previous.tasks || []).map((task) => [task.task_id, task]))
  const store = useCollaborationStore()

  for (const task of session.tasks || []) {
    const prior = previousTasks.get(task.task_id)
    if (!prior || prior.status === task.status || !TERMINAL_COLLABORATION_STATUSES.has(task.status)) continue
    const status = notificationStatus(task.status)
    if (!status) continue
    notifications.push({
      key: `collaboration-task:${task.task_id}:${status}`,
      category: 'collaboration',
      status,
      subject: store.agentById(task.assignee_package_id)?.agent_name || task.assignee_package_id,
      body: task.result_summary || task.task_text,
      target: {
        kind: 'collaboration',
        collaborationId: session.collaboration_id,
        taskId: task.task_id,
      },
    })
  }

  if (
    previous.status !== session.status
    && TERMINAL_COLLABORATION_STATUSES.has(session.status)
  ) {
    const status = notificationStatus(session.status)
    if (status) {
      notifications.push({
        key: `collaboration-session:${session.collaboration_id}:${status}`,
        category: 'collaboration',
        status,
        subject: session.title,
        body: session.messages?.at(-1)?.content || null,
        target: {
          kind: 'collaboration',
          collaborationId: session.collaboration_id,
        },
      })
    }
  }
  return notifications
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

function normalizedMode(
  mode: FactoryMode | null,
): 'create_agent' | 'evolve_agent' | 'agent_package' {
  if (mode === 'create_agent' || mode === 'evolve_agent' || mode === 'agent_package') return mode
  return 'agent_package'
}

function conversationSessionId(
  event: FactoryFrontendEvent,
  mode: 'create_agent' | 'evolve_agent' | 'agent_package',
): string | null {
  if (mode === 'agent_package') {
    return text(
      event.payload?.agent_session?.session_id
      || event.payload?.session_id
      || event.session_id,
    )
  }
  return text(
    event.payload?.factory_session_id
    || event.payload?.session?.session_id
    || event.payload?.session_id
    || event.session_id,
  )
}

function collaborationIdFromEvent(event: FactoryFrontendEvent): string | null {
  return text(
    event.payload?.collaboration_id
    || event.payload?.agent_session?.collaboration_id
    || event.payload?.session?.collaboration_id,
  )
}

function collaborationTaskIdFromEvent(event: FactoryFrontendEvent): string | null {
  return text(
    event.payload?.collaboration_task_id
    || event.payload?.agent_session?.collaboration_task_id
    || event.payload?.session?.collaboration_task_id,
  )
}

function eventSummary(event: FactoryFrontendEvent): string | null {
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

function findCollaborationTask(
  session: CollaborationSessionView | null,
  taskId: string,
): CollaborationTaskView | null {
  return session?.tasks?.find((task) => task.task_id === taskId) || null
}

function snapshotCollaborationSession(session: CollaborationSessionView): CollaborationSessionView {
  return {
    ...session,
    tasks: (session.tasks || []).map((task) => ({ ...task })),
    messages: (session.messages || []).map((message) => ({ ...message })),
  }
}

function text(value: unknown): string | null {
  const normalized = String(value || '').trim()
  return normalized || null
}
