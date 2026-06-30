/**
 * useEventStream Composable
 * 封装 SSE 事件流连接。运行类命令通过 HTTP 发出，实时事件通过这里进入 reducer。
 */

import { ref } from 'vue'
import { EventStreamClient, type ConnectionStatus } from '@/api/events'
import { useRuntimeStore } from '@/stores/runtime'
import { syncDomainStoresFromRuntime } from '@/stores/runtimeSync'
import { useUiStore } from '@/stores/ui'
import type { FactoryFrontendEvent } from '@/types/protocol'

let client: EventStreamClient | null = null
const status = ref<ConnectionStatus>('disconnected')
let initialized = false

export function applyRuntimeEvent(event: FactoryFrontendEvent): void {
  const runtimeStore = useRuntimeStore()
  runtimeStore.handleEvent(event)
  syncDomainStoresFromRuntime(event)
}

export function useEventStream() {
  const runtimeStore = useRuntimeStore()
  const uiStore = useUiStore()

  function connect() {
    if (client) return

    client = new EventStreamClient({
      url: '/events',
      onEvent: (event) => {
        applyRuntimeEvent(event)
      },
      onStatusChange: (newStatus) => {
        status.value = newStatus
        runtimeStore.connectionStatus = newStatus

        if (newStatus === 'connected') {
          uiStore.addNotification({
            type: 'success',
            title: '已连接',
            message: '事件流连接成功',
            duration: 3000,
          })
        } else if (newStatus === 'error') {
          uiStore.addNotification({
            type: 'error',
            title: '连接错误',
            message: '事件流连接失败',
            duration: 5000,
          })
        } else if (newStatus === 'reconnecting') {
          uiStore.addNotification({
            type: 'warning',
            title: '重新连接中',
            message: '正在恢复事件流...',
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
    if (!client) return
    client.disconnect()
    client = null
    initialized = false
  }

  return {
    status,
    initialized,
    connect,
    disconnect,
  }
}
