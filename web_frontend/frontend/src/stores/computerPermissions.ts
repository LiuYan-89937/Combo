import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { invoke, isTauri } from '@tauri-apps/api/core'
import { useRuntimePreferencesStore } from '@/stores/runtimePreferences'

type Permission = 'accessibility' | 'screen_recording'
interface ComputerPermissions {
  required: boolean
  accessibility: boolean
  screen_recording: boolean
}

// 引导只在用户尚未表态时展示一次；叉掉后不再自动出现，只能从设置里开启。
const DISMISSED_STORAGE_KEY = 'combo.computerUsePromptDismissed'

function readDismissed(): boolean {
  if (typeof window === 'undefined') return false
  return window.localStorage.getItem(DISMISSED_STORAGE_KEY) === 'true'
}

function writeDismissed(value: boolean): void {
  if (typeof window === 'undefined') return
  if (value) window.localStorage.setItem(DISMISSED_STORAGE_KEY, 'true')
  else window.localStorage.removeItem(DISMISSED_STORAGE_KEY)
}

export const useComputerPermissionsStore = defineStore('computerPermissions', () => {
  const runtimePreferences = useRuntimePreferencesStore()
  const status = ref<ComputerPermissions | null>(null)
  const busy = ref(false)
  const error = ref('')
  const dismissed = ref(readDismissed())
  let checking: Promise<boolean> | null = null

  // 用户是否启用 Computer Use。该偏好由后端持久化，未启用时后端不会向模型暴露 CU 工具。
  const enabled = computed(() => runtimePreferences.computerUseEnabled)
  // 系统权限是否齐备（非桌面端视为不需要）。
  const granted = computed(() => Boolean(status.value && (
    !status.value.required || (status.value.accessibility && status.value.screen_recording)
  )))
  const ready = computed(() => enabled.value && granted.value)
  // 仅用于首次引导：仅在确实需要系统权限、且用户尚未启用/未叉掉时自动弹出。
  const visible = computed(() => Boolean(
    status.value?.required && !enabled.value && !dismissed.value
  ))

  function dismiss(): void {
    dismissed.value = true
    writeDismissed(true)
  }

  function check(): Promise<boolean> {
    if (!isTauri()) {
      status.value = { required: false, accessibility: true, screen_recording: true }
      return Promise.resolve(ready.value)
    }
    if (checking) return checking
    checking = invoke<ComputerPermissions>('computer_permissions')
      .then((result) => {
        status.value = result
        error.value = ''
        // 系统权限被撤销时同步关闭偏好，避免在未授权状态下继续暴露 CU。
        if (enabled.value && !granted.value) runtimePreferences.setComputerUseEnabled(false)
        return ready.value
      })
      .catch((reason: unknown) => {
        status.value = null
        error.value = reason instanceof Error ? reason.message : String(reason)
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
      if (granted.value && !enabled.value) runtimePreferences.setComputerUseEnabled(true)
    } catch (reason) {
      error.value = reason instanceof Error ? reason.message : String(reason)
    } finally {
      busy.value = false
    }
  }

  /** 从设置中开启：必须先拿到系统权限，否则保持关闭。 */
  async function enable(): Promise<boolean> {
    if (enabled.value) return true
    await check()
    if (!granted.value) return false
    runtimePreferences.setComputerUseEnabled(true)
    return true
  }

  function disable(): void {
    runtimePreferences.setComputerUseEnabled(false)
  }

  return {
    status,
    visible,
    busy,
    error,
    enabled,
    granted,
    ready,
    dismissed,
    check,
    request,
    enable,
    disable,
    dismiss,
  }
})
