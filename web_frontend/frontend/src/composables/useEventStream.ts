/**
 * useEventStream Composable
 * 封装 SSE 事件流连接。运行类命令通过 HTTP 发出，实时事件通过这里进入 reducer。
 */

import { ref } from 'vue'
import { EventStreamClient, type ConnectionStatus } from '@/api/events'
import { useI18n } from '@/composables/useI18n'
import { useRuntimeStore } from '@/stores/runtime'
import { syncDomainStoresFromRuntime } from '@/stores/runtimeSync'
import { useAgentGroupStore } from '@/stores/agentGroup'
import { useUiStore } from '@/stores/ui'
import type { RuntimeFrontendEvent } from '@/types/protocol'
import { agentPackagesApi } from '@/api/agentPackages'
import { backendUrl } from '@/api/backendUrl'
import {
  captureTaskNotificationEventContext,
  publishTaskNotificationsForEvent,
} from '@/services/taskNotificationEvents'

let client: EventStreamClient | null = null
const status = ref<ConnectionStatus>('disconnected')
let initialized = false
let activeEventStreamId: string | null = null
const STREAM_RENDER_INTERVAL_MS = 32
const BATCHED_STREAM_EVENTS = new Set([
  'message_part_delta',
  'model_reasoning_delta',
  'model_stream_delta',
])
const BACKGROUND_TASK_TOOL_EVENTS = new Set([
  'tool_call_proposed',
  'tool_call_started',
  'tool_call_output_delta',
  'tool_call_completed',
  'tool_call_failed',
  'tool_contract_invalid',
  'tool_observation_available',
])
let pendingStreamEvents: RuntimeFrontendEvent[] = []
let streamFlushTimer: number | null = null

export function applyRuntimeEvent(event: RuntimeFrontendEvent): void {
  if (BATCHED_STREAM_EVENTS.has(event.event_type)) {
    enqueueStreamEvent(event)
    return
  }
  flushStreamEvents()
  applyRuntimeEventImmediately(event)
}

function applyRuntimeEventImmediately(event: RuntimeFrontendEvent): void {
  if (event.event_type === 'runtime_ready') {
    activeEventStreamId = String(event.payload?.event_stream_id || '').trim() || null
  }
  if (event.event_type === 'background_task_updated' && typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('combo:background-task-updated', { detail: event }))
  }
  if (
    typeof window !== 'undefined'
    && event.payload?.runtime_role === 'temporary'
    && event.payload?.source_task_id
    && BACKGROUND_TASK_TOOL_EVENTS.has(event.event_type)
  ) {
    window.dispatchEvent(new CustomEvent('combo:background-task-runtime-event', { detail: event }))
  }
  const notificationContext = captureTaskNotificationEventContext(event)
  if (event.payload?.group_id && event.payload?.group_run_id) {
    useAgentGroupStore().applyRuntimeEvent(event)
    publishTaskNotificationsForEvent(event, notificationContext)
    return
  }
  const runtimeStore = useRuntimeStore()
  runtimeStore.handleEvent(event)
  syncDomainStoresFromRuntime(event)
  publishTaskNotificationsForEvent(event, notificationContext)
  if (event.event_type === 'runtime_ready') {
    void restoreActiveConversation(runtimeStore).catch((error) => {
      console.error('Failed to restore active conversation after the event stream connected:', error)
    })
  }
}

function enqueueStreamEvent(event: RuntimeFrontendEvent): void {
  pendingStreamEvents.push(event)
  if (streamFlushTimer !== null) return
  streamFlushTimer = window.setTimeout(flushStreamEvents, STREAM_RENDER_INTERVAL_MS)
}

function flushStreamEvents(): void {
  if (streamFlushTimer !== null) {
    window.clearTimeout(streamFlushTimer)
    streamFlushTimer = null
  }
  if (pendingStreamEvents.length === 0) return
  const queued = pendingStreamEvents
  pendingStreamEvents = []
  for (const event of queued) {
    applyRuntimeEventImmediately(event)
  }
}

async function restoreActiveConversation(runtimeStore: ReturnType<typeof useRuntimeStore>): Promise<void> {
  if (runtimeStore.currentMode === 'agent_package' && runtimeStore.activeAgentSessionId) {
    const packageId = activeAgentPackageId(runtimeStore)
    if (!packageId) return
    const restored = await agentPackagesApi.session(packageId, runtimeStore.activeAgentSessionId)
    applyRuntimeEvent(restored)
    return
  }
}

function activeAgentPackageId(runtimeStore: ReturnType<typeof useRuntimeStore>): string | null {
  const selected = String(runtimeStore.selectedAgentPackage?.package_id || '').trim()
  if (selected) return selected
  const scope = String(runtimeStore.activeConversationScope || '')
  const parts = scope.split(':')
  return parts.length === 3 && parts[0] === 'agent_package' ? parts[1] || null : null
}

export function useEventStream() {
  const runtimeStore = useRuntimeStore()
  const uiStore = useUiStore()
  const { t } = useI18n()

  async function connect() {
    if (client) {
      client.ensureConnected()
      return
    }

    const eventUrl = await backendUrl('/events')
    if (client) return

    client = new EventStreamClient({
      url: eventUrl,
      onEvent: (event) => {
        applyRuntimeEvent(event)
      },
      onStatusChange: (newStatus) => {
        status.value = newStatus
        runtimeStore.connectionStatus = newStatus

        if (newStatus === 'connected') {
          uiStore.addNotification({
            type: 'success',
            title: t('connection.connected'),
            message: t('eventStream.connectedMessage'),
            duration: 3000,
          })
        } else if (newStatus === 'error') {
          uiStore.addNotification({
            type: 'error',
            title: t('connection.error'),
            message: t('eventStream.failedMessage'),
            duration: 5000,
          })
        } else if (newStatus === 'reconnecting') {
          uiStore.addNotification({
            type: 'warning',
            title: t('connection.reconnecting'),
            message: t('eventStream.reconnectingMessage'),
            duration: 3000,
          })
        }
      },
      onError: (error) => {
        console.error('Event stream error:', error)
      },
    })

    client.connect()
    initialized = true
  }

  function disconnect() {
    flushStreamEvents()
    if (!client) return
    client.disconnect()
    client = null
    activeEventStreamId = null
    initialized = false
  }

  return {
    status,
    initialized,
    connect,
    disconnect,
  }
}

export function ensureRuntimeEventStream(expectedStreamId?: string | null): void {
  const normalizedExpected = String(expectedStreamId || '').trim() || null
  if (client && normalizedExpected && activeEventStreamId !== normalizedExpected) {
    client.reconnect()
    return
  }
  client?.ensureConnected()
}
