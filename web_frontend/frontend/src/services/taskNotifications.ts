import type { Router } from 'vue-router'
import { translate, type I18nKey } from '@/i18n'
import { postCommand } from '@/api/http'
import { switchSessionCommand } from '@/api/commands'
import { useAgentGroupStore } from '@/stores/agentGroup'
import { useCollaborationStore } from '@/stores/collaboration'
import { useRuntimeStore } from '@/stores/runtime'
import { useTaskNotificationPreferencesStore, type TaskNotificationCategory } from '@/stores/taskNotificationPreferences'
import { useUiStore } from '@/stores/ui'

export type TaskNotificationStatus = 'completed' | 'failed' | 'cancelled' | 'skipped'

export type TaskNotificationTarget =
  | {
      kind: 'conversation'
      mode: 'create_agent' | 'evolve_agent' | 'agent_package'
      sessionId: string | null
      packageId: string | null
      collaborationId?: string | null
      collaborationTaskId?: string | null
      conversationScope?: string | null
    }
  | { kind: 'collaboration'; collaborationId: string; taskId?: string | null }
  | { kind: 'agentGroup'; groupId: string }
  | { kind: 'scheduler' }

export interface TaskTerminalNotification {
  key: string
  category: TaskNotificationCategory
  status: TaskNotificationStatus
  subject?: string | null
  body?: string | null
  target: TaskNotificationTarget
}

const SEEN_NOTIFICATION_STORAGE_KEY = 'fast-agent-factory.seenTaskNotifications'
const MAX_SEEN_NOTIFICATION_KEYS = 256
const MAX_NOTIFICATION_BODY_LENGTH = 240

let router: Router | null = null
let initialization: Promise<void> | null = null
const pendingNotifications: TaskTerminalNotification[] = []
const seenKeys = readSeenKeys()

export function initializeTaskNotifications(appRouter: Router): Promise<void> {
  router = appRouter
  if (initialization) return initialization
  initialization = initializeBrowserNotifications()
    .catch((error) => {
      console.warn('Browser task notifications are unavailable:', error)
    })
    .finally(() => {
      const pending = pendingNotifications.splice(0)
      pending.forEach((notification) => void deliverTaskNotification(notification))
    })
  return initialization
}

export function disposeTaskNotifications(): void {
  router = null
  initialization = null
}

export function publishTaskNotification(notification: TaskTerminalNotification): void {
  if (!router) {
    pendingNotifications.push(notification)
    return
  }
  void deliverTaskNotification(notification)
}

export async function requestTaskNotificationPermission(): Promise<boolean> {
  return ensureBrowserPermission(true)
}

async function initializeBrowserNotifications(): Promise<void> {
  const preferences = useTaskNotificationPreferencesStore()
  if (!preferences.active || typeof window === 'undefined' || !('Notification' in window)) return
  await ensureBrowserPermission(false)
}

async function deliverTaskNotification(notification: TaskTerminalNotification): Promise<void> {
  const preferences = useTaskNotificationPreferencesStore()
  if (!preferences.isCategoryEnabled(notification.category) || seenKeys.has(notification.key)) return
  rememberSeenKey(notification.key)

  if (await isCurrentTargetVisible(notification.target)) return

  const title = notificationTitle(notification)
  const body = compactBody(notification.body) || statusFallback(notification.status)
  const focused = await isAppFocused()
  if (focused) {
    showInAppNotification(notification, title, body)
    return
  }

  if (!(await ensureBrowserPermission(false))) {
    showInAppNotification(notification, title, body)
    return
  }

  showBrowserNotification(notification, title, body)
}

function showInAppNotification(
  notification: TaskTerminalNotification,
  title: string,
  body: string,
): void {
  useUiStore().addNotification({
    type: notification.status === 'completed'
      ? 'success'
      : notification.status === 'skipped'
        ? 'warning'
        : 'error',
    title,
    message: body,
    duration: notification.status === 'completed' ? 8000 : 10000,
    actionLabel: translate(useUiStore().locale, 'common.view'),
    onAction: () => openNotificationTargetSafely(notification.target),
  })
}

async function ensureBrowserPermission(requestIfMissing: boolean): Promise<boolean> {
  if (typeof window === 'undefined' || !('Notification' in window)) return false
  if (Notification.permission === 'granted') return true
  if (!requestIfMissing) return false
  return (await Notification.requestPermission()) === 'granted'
}

async function isAppFocused(): Promise<boolean> {
  if (typeof document === 'undefined') return false
  return document.visibilityState === 'visible' && document.hasFocus()
}

async function isCurrentTargetVisible(target: TaskNotificationTarget): Promise<boolean> {
  if (!(await isAppFocused()) || !router) return false
  const routeName = String(router.currentRoute.value.name || '')
  if (target.kind === 'scheduler') return routeName === 'Scheduler'
  if (target.kind === 'agentGroup') {
    return routeName === 'AgentGroup' && useAgentGroupStore().activeGroup?.group_id === target.groupId
  }
  if (target.kind === 'collaboration') {
    return routeName === 'Collaboration'
      && useCollaborationStore().activeSession?.collaboration_id === target.collaborationId
  }
  if (!['Factory', 'Manufacturing', 'Evolution'].includes(routeName)) return false
  const runtimeStore = useRuntimeStore()
  if (target.conversationScope) {
    return runtimeStore.activeConversationScope === target.conversationScope
  }
  return target.mode === 'agent_package'
    ? runtimeStore.activeAgentSessionId === target.sessionId
    : runtimeStore.activeFactorySessionId === target.sessionId
}

async function openNotificationTarget(target: TaskNotificationTarget): Promise<void> {
  if (!router) return
  const focusPromise = focusApplicationWindow().catch((error) => {
    console.warn('Failed to focus the application window:', error)
  })
  if (target.kind === 'scheduler') {
    await router.push({ name: 'Scheduler' })
    await focusPromise
    return
  }
  if (target.kind === 'agentGroup') {
    await router.push({ name: 'AgentGroup' })
    await useAgentGroupStore().loadGroup(target.groupId)
    await focusPromise
    return
  }
  if (target.kind === 'collaboration') {
    await router.push({ name: 'Collaboration' })
    await useCollaborationStore().loadSession(target.collaborationId)
    await focusPromise
    return
  }
  if (target.mode === 'agent_package' && target.packageId && target.sessionId) {
    await router.push({
      name: 'Factory',
      query: {
        package_id: target.packageId,
        session_id: target.sessionId,
        collaboration_id: target.collaborationId || undefined,
        collaboration_task_id: target.collaborationTaskId || undefined,
      },
    })
    await focusPromise
    return
  }
  const routeName = target.mode === 'create_agent'
    ? 'Manufacturing'
    : target.mode === 'evolve_agent'
      ? 'Evolution'
      : 'Factory'
  await router.push({ name: routeName })
  if (target.sessionId) {
    await postCommand(switchSessionCommand(target.sessionId, target.mode))
  }
  await focusPromise
}

function openNotificationTargetSafely(target: TaskNotificationTarget): void {
  void openNotificationTarget(target).catch((error) => {
    console.warn('Failed to open task notification target:', error)
  })
}

async function focusApplicationWindow(): Promise<void> {
  window.focus()
}

function notificationTitle(notification: TaskTerminalNotification): string {
  const locale = useUiStore().locale
  const subject = String(notification.subject || '').trim()
    || translate(locale, categoryTitleKey(notification.category))
  return translate(locale, 'taskNotification.title', {
    subject,
    status: translate(locale, statusTitleKey(notification.status)),
  })
}

function categoryTitleKey(category: TaskNotificationCategory): I18nKey {
  const keys: Record<TaskNotificationCategory, I18nKey> = {
    conversation: 'taskNotification.conversation',
    collaboration: 'taskNotification.collaboration',
    agentGroup: 'taskNotification.agentGroup',
    scheduler: 'taskNotification.scheduler',
  }
  return keys[category]
}

function statusTitleKey(status: TaskNotificationStatus): I18nKey {
  const keys: Record<TaskNotificationStatus, I18nKey> = {
    completed: 'taskNotification.completed',
    failed: 'taskNotification.failed',
    cancelled: 'taskNotification.cancelled',
    skipped: 'taskNotification.skipped',
  }
  return keys[status]
}

function statusFallback(status: TaskNotificationStatus): string {
  return translate(useUiStore().locale, statusTitleKey(status))
}

function compactBody(value: string | null | undefined): string {
  const normalized = String(value || '').replace(/\s+/g, ' ').trim()
  if (normalized.length <= MAX_NOTIFICATION_BODY_LENGTH) return normalized
  return `${normalized.slice(0, MAX_NOTIFICATION_BODY_LENGTH - 1)}…`
}

function showBrowserNotification(
  notification: TaskTerminalNotification,
  title: string,
  body: string,
): void {
  const browserNotification = new Notification(title, {
    body,
    tag: notification.key,
  })
  browserNotification.onclick = () => {
    browserNotification.close()
    window.focus()
    openNotificationTargetSafely(notification.target)
  }
}

function readSeenKeys(): Set<string> {
  if (typeof window === 'undefined') return new Set()
  try {
    const stored = JSON.parse(window.localStorage.getItem(SEEN_NOTIFICATION_STORAGE_KEY) || '[]')
    return new Set(Array.isArray(stored) ? stored.map(String) : [])
  } catch {
    return new Set()
  }
}

function rememberSeenKey(key: string): void {
  seenKeys.add(key)
  while (seenKeys.size > MAX_SEEN_NOTIFICATION_KEYS) {
    const oldest = seenKeys.values().next().value
    if (oldest === undefined) break
    seenKeys.delete(oldest)
  }
  if (typeof window !== 'undefined') {
    window.localStorage.setItem(SEEN_NOTIFICATION_STORAGE_KEY, JSON.stringify([...seenKeys]))
  }
}
