import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { invoke, isTauri } from '@tauri-apps/api/core'

type Permission = 'accessibility' | 'screen_recording'
interface ComputerPermissions {
  required: boolean
  accessibility: boolean
  screen_recording: boolean
}

export const useComputerPermissionsStore = defineStore('computerPermissions', () => {
  const status = ref<ComputerPermissions | null>(null)
  const visible = ref(false)
  const busy = ref(false)
  const error = ref('')
  const ready = computed(() => Boolean(status.value && (
    !status.value.required || (status.value.accessibility && status.value.screen_recording)
  )))
  let checking: Promise<boolean> | null = null

  function check(): Promise<boolean> {
    if (!isTauri()) return Promise.resolve(true)
    if (checking) return checking
    checking = invoke<ComputerPermissions>('computer_permissions')
      .then((result) => {
        status.value = result
        error.value = ''
        visible.value = !ready.value
        return ready.value
      })
      .catch((reason: unknown) => {
        status.value = null
        error.value = reason instanceof Error ? reason.message : String(reason)
        visible.value = true
        return false
      })
      .finally(() => { checking = null })
    return checking
  }

  async function request(permission: Permission): Promise<void> {
    if (busy.value) return
    busy.value = true
    error.value = ''
    try {
      status.value = await invoke<ComputerPermissions>('request_computer_permission', { permission })
      visible.value = !ready.value
    } catch (reason) {
      error.value = reason instanceof Error ? reason.message : String(reason)
    } finally {
      busy.value = false
    }
  }

  return { status, visible, busy, error, ready, check, request }
})
