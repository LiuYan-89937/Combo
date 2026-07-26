import { isTauri } from '@tauri-apps/api/core'
import { getCurrentWindow } from '@tauri-apps/api/window'
import {
  isPermissionGranted,
  onAction,
  requestPermission,
  sendNotification,
  type Options as NativeNotificationOptions,
} from '@tauri-apps/plugin-notification'
import type { PluginListener } from '@tauri-apps/api/core'
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
      mode: 'chat' | 'create_agent' | 'evolve_agent' | 'agent_package'
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
const NATIVE_TARGET_EXTRA_KEY = 'fastAgentFactoryTarget'

let router: Router | null = null
let nativeActionListener: PluginListener | null = null
let initialization: Promise<void> | null = null
const pendingNotifications: TaskTerminalNotification[] = []
const seenKeys = readSeenKeys()

export function initializeTaskNotifications(appRouter: Router): Promise<void> {
  router = appRouter
  if (initialization) return initialization
  initialization = initializeNativeNotifications()
    .catch((error) => {
      console.warn('Native task notifications are unavailable:', error)
    })
    .finally(() => {
      const pending = pendingNotifications.splice(0)
      pending.forEach((notification) => void deliverTaskNotification(notification))
    })
  return initialization
}

export function disposeTaskNotifications(): void {
  nativeActionListener?.unregister()
  nativeActionListener = null
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

export async function requestNativeTaskNotificationPermission(): Promise<boolean> {
  return ensureNativePermission(true)
}

async function initializeNativeNotifications(): Promise<void> {
  if (!isTauri()) return
  nativeActionListener = await onAction((notification) => {
    const target = targetFromNativeNotification(notification)
    if (target) void openNotificationTarget(target)
  })
  const preferences = useTaskNotificationPreferencesStore()
  if (preferences.active) await ensureNativePermission(true)
}

async function deliverTaskNotification(notification: TaskTerminalNotification): Promise<void> {
  const preferences = useTaskNotificationPreferencesStore()
  if (!preferences.isCategoryEnabled(notification.category) || seenKeys.has(notification.key)) return
  rememberSeenKey(notification.key)

  if (await isCurrentTargetVisible(notification.target)) return

  const title = notificationTitle(notification)
  const body = compactBody(notification.body) || statusFallback(notification.status)
  const focused = await isAppFocused()
  if (focused || !isTauri()) {
    showInAppNotification(notification, title, body)
    return
  }

  if (!(await ensureNativePermission(false))) {
    showInAppNotification(notification, title, body)
    return
  }

  sendNotification({
    id: stableNotificationId(notification.key),
    title,
    body,
    autoCancel: true,
    group: notification.category,
    extra: {
      [NATIVE_TARGET_EXTRA_KEY]: JSON.stringify(notification.target),
    },
  })
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
    onAction: () => void openNotificationTarget(notification.target),
  })
}

async function ensureNativePermission(requestIfMissing: boolean): Promise<boolean> {
  if (!isTauri()) return false
  if (await isPermissionGranted()) return true
  if (!requestIfMissing) return false
  return (await requestPermission()) === 'granted'
}

async function isAppFocused(): Promise<boolean> {
  if (typeof document === 'undefined') return false
  if (document.visibilityState !== 'visible' || !document.hasFocus()) return false
  if (!isTauri()) return true
  try {
    return await getCurrentWindow().isFocused()
  } catch {
    return document.hasFocus()
  }
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
  await focusApplicationWindow()
  if (target.kind === 'scheduler') {
    await router.push({ name: 'Scheduler' })
    return
  }
  if (target.kind === 'agentGroup') {
    await router.push({ name: 'AgentGroup' })
    await useAgentGroupStore().loadGroup(target.groupId)
    return
  }
  if (target.kind === 'collaboration') {
    await router.push({ name: 'Collaboration' })
    await useCollaborationStore().loadSession(target.collaborationId)
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
}

async function focusApplicationWindow(): Promise<void> {
  if (!isTauri()) return
  const window = getCurrentWindow()
  await window.unminimize()
  await window.show()
  await window.setFocus()
}

function targetFromNativeNotification(notification: NativeNotificationOptions): TaskNotificationTarget | null {
  const serialized = notification.extra?.[NATIVE_TARGET_EXTRA_KEY]
  if (typeof serialized !== 'string') return null
  try {
    return JSON.parse(serialized) as TaskNotificationTarget
  } catch {
    return null
  }
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

function stableNotificationId(value: string): number {
  let hash = 0
  for (let index = 0; index < value.length; index += 1) {
    hash = ((hash << 5) - hash + value.charCodeAt(index)) | 0
  }
  return hash
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
