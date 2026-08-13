import { defineStore } from 'pinia'
import { ref } from 'vue'
import { REASONING_INTENSITY_MAX } from '@/utils/reasoning'
import { runtimePreferencesApi, type RuntimePreferences, type RuntimePreferencesPatch } from '@/api/runtimePreferences'
import type { ApprovalMode, ExecutionPreference } from '@/api/dynamicRuntime'

export const DEFAULT_RUNTIME_REQUEST_TIMEOUT_SECONDS = 300
export const DEFAULT_RUNTIME_MAX_RETRIES = 5
export const DEFAULT_MAX_PARALLEL_SUB_AGENTS = 5
export const DEFAULT_APPROVAL_MODE: ApprovalMode = 'ask'
export const DEFAULT_EXECUTION_PREFERENCE: ExecutionPreference = 'auto'
export const DEFAULT_MEMORY_WRITE_INTERVAL_TURNS = 3
export const DEFAULT_MEMORY_MAX_INJECTED_ITEMS = 8
export const DEFAULT_MEMORY_MAX_INJECTED_TOKENS = 1200

const STORAGE_KEYS = {
  mainModelProfileId: 'fast-agent-factory.runtimeMainModelProfileId',
  reasoningIntensity: 'fastagentfactory.runtimeReasoningIntensity',
  requestTimeoutSeconds: 'fast-agent-factory.runtimeRequestTimeoutSeconds',
  maxRetries: 'fast-agent-factory.runtimeMaxRetries',
  maxParallelSubAgents: 'fast-agent-factory.maxParallelSubAgents',
  approvalMode: 'fast-agent-factory.approvalMode',
  executionPreference: 'fast-agent-factory.executionPreference',
} as const

export const useRuntimePreferencesStore = defineStore('runtimePreferences', () => {
  const mainModelProfileId = ref(readStoredText(STORAGE_KEYS.mainModelProfileId))
  const reasoningIntensity = ref<number | null>(readStoredReasoningIntensity())
  const requestTimeoutSeconds = ref(readStoredInteger(STORAGE_KEYS.requestTimeoutSeconds, DEFAULT_RUNTIME_REQUEST_TIMEOUT_SECONDS, 0))
  const maxRetries = ref(readStoredInteger(STORAGE_KEYS.maxRetries, DEFAULT_RUNTIME_MAX_RETRIES, 0))
  const maxParallelSubAgents = ref(readStoredInteger(STORAGE_KEYS.maxParallelSubAgents, DEFAULT_MAX_PARALLEL_SUB_AGENTS, 1))
  const approvalMode = ref<ApprovalMode>(readStoredApprovalMode())
  const executionPreference = ref<ExecutionPreference>(readStoredExecutionPreference())
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
    maxRetries,
    maxParallelSubAgents,
    approvalMode,
    executionPreference,
    memoryAutoWriteEnabled,
    memoryWriteIntervalTurns,
    memoryAgentWriteEnabled,
    memoryMaxInjectedItems,
    memoryMaxInjectedTokens,
    maxParallelSubAgentsSaveFailed,
    setMainModelProfileId,
    setReasoningIntensity,
    setRequestTimeoutSeconds,
    setMaxRetries,
    setMaxParallelSubAgents,
    setApprovalMode,
    setExecutionPreference,
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
  return value === 'react' || value === 'plan_and_execute' || value === 'auto'
    ? value
    : DEFAULT_EXECUTION_PREFERENCE
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
