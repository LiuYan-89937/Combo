import { defineStore } from 'pinia'
import { ref } from 'vue'
import { REASONING_INTENSITY_MAX } from '@/utils/reasoning'
import { runtimePreferencesApi, type RuntimePreferences, type RuntimePreferencesPatch } from '@/api/runtimePreferences'
import type { ApprovalMode, ExecutionPreference } from '@/api/dynamicRuntime'

export const DEFAULT_RUNTIME_REQUEST_TIMEOUT_SECONDS = 300
export const DEFAULT_BROWSER_OPERATION_TIMEOUT_MS = 30_000
export const DEFAULT_BROWSER_NAVIGATION_TIMEOUT_MS = 45_000
export const DEFAULT_RUNTIME_MAX_RETRIES = 5
export const DEFAULT_MAX_PARALLEL_SUB_AGENTS = 5
export const DEFAULT_APPROVAL_MODE: ApprovalMode = 'ask'
export const DEFAULT_EXECUTION_PREFERENCE: ExecutionPreference = 'react'
export const DEFAULT_MEMORY_WRITE_INTERVAL_TURNS = 3
export const DEFAULT_MEMORY_MAX_INJECTED_ITEMS = 8
export const DEFAULT_MEMORY_MAX_INJECTED_TOKENS = 1200
export type RunningMessageMode = 'queue' | 'steer'
export const DEFAULT_RUNNING_MESSAGE_MODE: RunningMessageMode = 'queue'

const STORAGE_KEYS = {
  mainModelProfileId: 'combo.runtimeMainModelProfileId',
  reasoningIntensity: 'combo.runtimeReasoningIntensity',
  requestTimeoutSeconds: 'combo.runtimeRequestTimeoutSeconds',
  maxRetries: 'combo.runtimeMaxRetries',
  maxParallelSubAgents: 'combo.maxParallelSubAgents',
  approvalMode: 'combo.approvalMode',
  executionPreference: 'combo.executionPreference',
  forceCollaboration: 'combo.forceCollaboration',
  runningMessageMode: 'combo.runningMessageMode',
} as const

export const useRuntimePreferencesStore = defineStore('runtimePreferences', () => {
  const mainModelProfileId = ref(readStoredText(STORAGE_KEYS.mainModelProfileId))
  const reasoningIntensity = ref<number | null>(readStoredReasoningIntensity())
  const requestTimeoutSeconds = ref(readStoredInteger(STORAGE_KEYS.requestTimeoutSeconds, DEFAULT_RUNTIME_REQUEST_TIMEOUT_SECONDS, 0))
  const browserOperationTimeoutMs = ref(DEFAULT_BROWSER_OPERATION_TIMEOUT_MS)
  const browserNavigationTimeoutMs = ref(DEFAULT_BROWSER_NAVIGATION_TIMEOUT_MS)
  const maxRetries = ref(readStoredInteger(STORAGE_KEYS.maxRetries, DEFAULT_RUNTIME_MAX_RETRIES, 0))
  const maxParallelSubAgents = ref(readStoredInteger(STORAGE_KEYS.maxParallelSubAgents, DEFAULT_MAX_PARALLEL_SUB_AGENTS, 1))
  const approvalMode = ref<ApprovalMode>(readStoredApprovalMode())
  const executionPreference = ref<ExecutionPreference>(readStoredExecutionPreference())
  const forceCollaboration = ref(readStoredBoolean(STORAGE_KEYS.forceCollaboration))
  const runningMessageMode = ref<RunningMessageMode>(readStoredRunningMessageMode())
  const memoryAutoWriteEnabled = ref(true)
  const memoryWriteIntervalTurns = ref(DEFAULT_MEMORY_WRITE_INTERVAL_TURNS)
  const memoryAgentWriteEnabled = ref(true)
  const memoryMaxInjectedItems = ref(DEFAULT_MEMORY_MAX_INJECTED_ITEMS)
  const memoryMaxInjectedTokens = ref(DEFAULT_MEMORY_MAX_INJECTED_TOKENS)
  const maxParallelSubAgentsSaveFailed = ref(false)
  const revision = ref(0)
  let pendingPatch: RuntimePreferencesPatch = {}
  let saveLoop: Promise<void> | null = null

  function setMainModelProfileId(value: string): void {
    mainModelProfileId.value = String(value || '').trim()
    writeOrRemove(STORAGE_KEYS.mainModelProfileId, mainModelProfileId.value)
    enqueue({ model_profile_id: mainModelProfileId.value || null })
  }

  function setReasoningIntensity(value: number | null): void {
    reasoningIntensity.value = value === null
      ? null
      : Math.max(0, Math.min(REASONING_INTENSITY_MAX, Math.round(value)))
    writeNullableNumber(STORAGE_KEYS.reasoningIntensity, reasoningIntensity.value)
    enqueue({ reasoning_intensity: reasoningIntensity.value })
  }

  function setRequestTimeoutSeconds(value: number): void {
    requestTimeoutSeconds.value = Math.max(0, Math.round(value))
    writeStoredValue(STORAGE_KEYS.requestTimeoutSeconds, String(requestTimeoutSeconds.value))
    enqueue({ request_timeout_seconds: requestTimeoutSeconds.value })
  }

  function setBrowserOperationTimeoutMs(value: number): void {
    browserOperationTimeoutMs.value = Math.max(1_000, Math.round(value))
    enqueue({ browser_operation_timeout_ms: browserOperationTimeoutMs.value })
  }

  function setBrowserNavigationTimeoutMs(value: number): void {
    browserNavigationTimeoutMs.value = Math.max(1_000, Math.round(value))
    enqueue({ browser_navigation_timeout_ms: browserNavigationTimeoutMs.value })
  }

  function setMaxRetries(value: number): void {
    maxRetries.value = Math.max(0, Math.round(value))
    writeStoredValue(STORAGE_KEYS.maxRetries, String(maxRetries.value))
    enqueue({ max_retries: maxRetries.value })
  }

  function setMaxParallelSubAgents(value: number): void {
    maxParallelSubAgents.value = Math.max(1, Math.round(value))
    writeStoredValue(STORAGE_KEYS.maxParallelSubAgents, String(maxParallelSubAgents.value))
    enqueue({ max_parallel_sub_agents: maxParallelSubAgents.value })
  }

  function setApprovalMode(value: ApprovalMode): void {
    approvalMode.value = value
    writeStoredValue(STORAGE_KEYS.approvalMode, value)
    enqueue({ approval_mode: value })
  }

  function setExecutionPreference(value: ExecutionPreference): void {
    executionPreference.value = value
    writeStoredValue(STORAGE_KEYS.executionPreference, value)
    enqueue({ execution_preference: value })
  }

  function setForceCollaboration(value: boolean): void {
    forceCollaboration.value = value
    if (value) writeStoredValue(STORAGE_KEYS.forceCollaboration, 'true')
    else removeStoredValue(STORAGE_KEYS.forceCollaboration)
  }

  function setRunningMessageMode(value: RunningMessageMode): void {
    runningMessageMode.value = value
    writeStoredValue(STORAGE_KEYS.runningMessageMode, value)
  }

  function setMemoryAutoWriteEnabled(value: boolean): void {
    memoryAutoWriteEnabled.value = value
    enqueue({ memory_auto_write_enabled: value })
  }

  function setMemoryWriteIntervalTurns(value: number): void {
    memoryWriteIntervalTurns.value = Math.max(1, Math.round(value))
    enqueue({ memory_write_interval_turns: memoryWriteIntervalTurns.value })
  }

  function setMemoryAgentWriteEnabled(value: boolean): void {
    memoryAgentWriteEnabled.value = value
    enqueue({ memory_agent_write_enabled: value })
  }

  function setMemoryMaxInjectedItems(value: number): void {
    memoryMaxInjectedItems.value = Math.max(1, Math.round(value))
    enqueue({ memory_max_injected_items: memoryMaxInjectedItems.value })
  }

  function setMemoryMaxInjectedTokens(value: number): void {
    memoryMaxInjectedTokens.value = Math.max(100, Math.round(value))
    enqueue({ memory_max_injected_tokens: memoryMaxInjectedTokens.value })
  }

  async function refreshRuntimePreferences(): Promise<void> {
    apply(await runtimePreferencesApi.get())
    maxParallelSubAgentsSaveFailed.value = false
  }

  function enqueue(patch: RuntimePreferencesPatch): void {
    pendingPatch = { ...pendingPatch, ...patch }
    if (!saveLoop) {
      saveLoop = drain().finally(() => { saveLoop = null })
    }
  }

  async function drain(): Promise<void> {
    await initialization
    while (Object.keys(pendingPatch).length > 0) {
      const patch = pendingPatch
      pendingPatch = {}
      try {
        apply(await runtimePreferencesApi.update(patch, revision.value))
        maxParallelSubAgentsSaveFailed.value = false
      } catch (error) {
        if (Number((error as { status?: unknown })?.status) === 409) {
          await refreshRuntimePreferences()
          pendingPatch = { ...patch, ...pendingPatch }
          continue
        }
        pendingPatch = { ...patch, ...pendingPatch }
        maxParallelSubAgentsSaveFailed.value = true
        return
      }
    }
  }

  function apply(value: RuntimePreferences): void {
    revision.value = value.revision
    mainModelProfileId.value = value.model_profile_id || ''
    reasoningIntensity.value = value.reasoning_intensity
    approvalMode.value = value.approval_mode
    executionPreference.value = value.execution_preference
    requestTimeoutSeconds.value = value.request_timeout_seconds
    browserOperationTimeoutMs.value = value.browser_operation_timeout_ms
    browserNavigationTimeoutMs.value = value.browser_navigation_timeout_ms
    maxRetries.value = value.max_retries
    maxParallelSubAgents.value = value.max_parallel_sub_agents
    memoryAutoWriteEnabled.value = value.memory_auto_write_enabled
    memoryWriteIntervalTurns.value = value.memory_write_interval_turns
    memoryAgentWriteEnabled.value = value.memory_agent_write_enabled
    memoryMaxInjectedItems.value = value.memory_max_injected_items
    memoryMaxInjectedTokens.value = value.memory_max_injected_tokens
    writeOrRemove(STORAGE_KEYS.mainModelProfileId, mainModelProfileId.value)
    writeNullableNumber(STORAGE_KEYS.reasoningIntensity, reasoningIntensity.value)
    writeStoredValue(STORAGE_KEYS.approvalMode, approvalMode.value)
    writeStoredValue(STORAGE_KEYS.executionPreference, executionPreference.value)
    writeStoredValue(STORAGE_KEYS.requestTimeoutSeconds, String(requestTimeoutSeconds.value))
    writeStoredValue(STORAGE_KEYS.maxRetries, String(maxRetries.value))
    writeStoredValue(STORAGE_KEYS.maxParallelSubAgents, String(maxParallelSubAgents.value))
  }

  const initialization = refreshRuntimePreferences().catch(() => undefined)

  return {
    mainModelProfileId,
    reasoningIntensity,
    requestTimeoutSeconds,
    browserOperationTimeoutMs,
    browserNavigationTimeoutMs,
    maxRetries,
    maxParallelSubAgents,
    approvalMode,
    executionPreference,
    forceCollaboration,
    runningMessageMode,
    memoryAutoWriteEnabled,
    memoryWriteIntervalTurns,
    memoryAgentWriteEnabled,
    memoryMaxInjectedItems,
    memoryMaxInjectedTokens,
    maxParallelSubAgentsSaveFailed,
    setMainModelProfileId,
    setReasoningIntensity,
    setRequestTimeoutSeconds,
    setBrowserOperationTimeoutMs,
    setBrowserNavigationTimeoutMs,
    setMaxRetries,
    setMaxParallelSubAgents,
    setApprovalMode,
    setExecutionPreference,
    setForceCollaboration,
    setRunningMessageMode,
    setMemoryAutoWriteEnabled,
    setMemoryWriteIntervalTurns,
    setMemoryAgentWriteEnabled,
    setMemoryMaxInjectedItems,
    setMemoryMaxInjectedTokens,
    refreshMaxParallelSubAgents: refreshRuntimePreferences,
    refreshRuntimePreferences,
  }
})

function readStoredText(key: string): string {
  if (typeof window === 'undefined') return ''
  return String(window.localStorage.getItem(key) || '').trim()
}
function readStoredReasoningIntensity(): number | null {
  const stored = readStoredText(STORAGE_KEYS.reasoningIntensity)
  const value = Number(stored)
  return stored && Number.isInteger(value) && value >= 0 && value <= REASONING_INTENSITY_MAX ? value : null
}

function readStoredRunningMessageMode(): RunningMessageMode {
  return readStoredText(STORAGE_KEYS.runningMessageMode) === 'steer' ? 'steer' : DEFAULT_RUNNING_MESSAGE_MODE
}
function readStoredInteger(key: string, fallback: number, minimum: number): number {
  const value = Number(readStoredText(key))
  return Number.isInteger(value) && value >= minimum ? value : fallback
}
function readStoredApprovalMode(): ApprovalMode {
  const value = readStoredText(STORAGE_KEYS.approvalMode)
  return value === 'auto' || value === 'always_approval' || value === 'ask' ? value : DEFAULT_APPROVAL_MODE
}
function readStoredExecutionPreference(): ExecutionPreference {
  const value = readStoredText(STORAGE_KEYS.executionPreference)
  return value === 'plan_and_execute' ? value : DEFAULT_EXECUTION_PREFERENCE
}
function readStoredBoolean(key: string): boolean {
  return readStoredText(key) === 'true'
}
function writeNullableNumber(key: string, value: number | null): void {
  if (value === null) removeStoredValue(key)
  else writeStoredValue(key, String(value))
}
function writeOrRemove(key: string, value: string): void {
  if (value) writeStoredValue(key, value)
  else removeStoredValue(key)
}
function writeStoredValue(key: string, value: string): void {
  if (typeof window !== 'undefined') window.localStorage.setItem(key, value)
}
function removeStoredValue(key: string): void {
  if (typeof window !== 'undefined') window.localStorage.removeItem(key)
}
