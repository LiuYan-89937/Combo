import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { initializeBackendUrl, restartBackend, waitForBackendReady } from '@/api/backendUrl'

type StartupStatus = 'idle' | 'initializing' | 'succeeded' | 'ready' | 'failed'

const SUCCESS_TRANSITION_DURATION = 1100

export const useStartupStore = defineStore('startup', () => {
  const status = ref<StartupStatus>('idle')
  const error = ref('')
  let initialization: Promise<void> | null = null

  const ready = computed(() => status.value === 'ready')
  const initializing = computed(() => status.value === 'idle' || status.value === 'initializing')

  function initialize(): Promise<void> {
    if (initialization) return initialization
    status.value = 'initializing'
    error.value = ''
    initialization = initializeBackendUrl()
      .then(() => waitForBackendReady())
      .then(async () => {
        status.value = 'succeeded'
        await new Promise(resolve => window.setTimeout(resolve, SUCCESS_TRANSITION_DURATION))
        status.value = 'ready'
      })
      .catch((reason: unknown) => {
        status.value = 'failed'
        error.value = reason instanceof Error ? reason.message : String(reason)
        throw reason
      })
      .finally(() => {
        initialization = null
      })
    return initialization
  }

  function retry(): void {
    if (status.value === 'initializing') return
    status.value = 'initializing'
    error.value = ''
    void restartBackend()
      .then(() => initialize())
      .catch((reason: unknown) => {
        status.value = 'failed'
        error.value = reason instanceof Error ? reason.message : String(reason)
      })
  }

  return {
    status,
    error,
    ready,
    initializing,
    initialize,
    retry,
  }
})
