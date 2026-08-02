import { defineStore } from 'pinia'
import { ref } from 'vue'
import { REASONING_INTENSITY_MAX } from '@/utils/reasoning'

export const DEFAULT_RUNTIME_REQUEST_TIMEOUT_SECONDS = 300
export const DEFAULT_RUNTIME_MAX_RETRIES = 5
export const DEFAULT_MAX_PARALLEL_SUB_AGENTS = 5

const STORAGE_KEYS = {
  mainModelProfileId: 'fast-agent-factory.runtimeMainModelProfileId',
  reasoningIntensity: 'fastagentfactory.runtimeReasoningIntensity',
  requestTimeoutSeconds: 'fast-agent-factory.runtimeRequestTimeoutSeconds',
  maxRetries: 'fast-agent-factory.runtimeMaxRetries',
  maxParallelSubAgents: 'fast-agent-factory.maxParallelSubAgents',
} as const

export const useRuntimePreferencesStore = defineStore('runtimePreferences', () => {
  const mainModelProfileId = ref(readStoredText(STORAGE_KEYS.mainModelProfileId))
  const reasoningIntensity = ref<number | null>(readStoredReasoningIntensity())
  const requestTimeoutSeconds = ref(readStoredRequestTimeoutSeconds())
  const maxRetries = ref(readStoredMaxRetries())
  const maxParallelSubAgents = ref(readStoredMaxParallelSubAgents())

  function setMainModelProfileId(profileId: string): void {
    mainModelProfileId.value = String(profileId || '').trim()
    writeOrRemove(STORAGE_KEYS.mainModelProfileId, mainModelProfileId.value)
  }

  function setReasoningIntensity(value: number | null): void {
    if (value === null) {
      reasoningIntensity.value = null
      removeStoredValue(STORAGE_KEYS.reasoningIntensity)
      return
    }
    const normalized = Math.max(0, Math.min(REASONING_INTENSITY_MAX, Math.round(value)))
    reasoningIntensity.value = normalized
    writeStoredValue(STORAGE_KEYS.reasoningIntensity, String(normalized))
  }

  function setRequestTimeoutSeconds(value: number): void {
    const normalized = Math.max(0, Math.round(value))
    requestTimeoutSeconds.value = normalized
    writeStoredValue(STORAGE_KEYS.requestTimeoutSeconds, String(normalized))
  }

  function setMaxRetries(value: number): void {
    const normalized = Math.max(0, Math.round(value))
    maxRetries.value = normalized
    writeStoredValue(STORAGE_KEYS.maxRetries, String(normalized))
  }

  function setMaxParallelSubAgents(value: number): void {
    const normalized = Math.max(1, Math.round(value))
    maxParallelSubAgents.value = normalized
    writeStoredValue(STORAGE_KEYS.maxParallelSubAgents, String(normalized))
  }

  return {
    mainModelProfileId,
    reasoningIntensity,
    requestTimeoutSeconds,
    maxRetries,
    maxParallelSubAgents,
    setMainModelProfileId,
    setReasoningIntensity,
    setRequestTimeoutSeconds,
    setMaxRetries,
    setMaxParallelSubAgents,
  }
})

function readStoredText(key: string): string {
  if (typeof window === 'undefined') return ''
  return String(window.localStorage.getItem(key) || '').trim()
}

function readStoredReasoningIntensity(): number | null {
  const stored = readStoredText(STORAGE_KEYS.reasoningIntensity)
  if (!stored) return null
  const value = Number(stored)
  return Number.isInteger(value) && value >= 0 && value <= REASONING_INTENSITY_MAX ? value : null
}

function readStoredRequestTimeoutSeconds(): number {
  const stored = readStoredText(STORAGE_KEYS.requestTimeoutSeconds)
  if (!stored) return DEFAULT_RUNTIME_REQUEST_TIMEOUT_SECONDS
  const value = Number(stored)
  return Number.isInteger(value) && value >= 0 ? value : DEFAULT_RUNTIME_REQUEST_TIMEOUT_SECONDS
}

function readStoredMaxRetries(): number {
  const stored = readStoredText(STORAGE_KEYS.maxRetries)
  if (!stored) return DEFAULT_RUNTIME_MAX_RETRIES
  const value = Number(stored)
  return Number.isInteger(value) && value >= 0 ? value : DEFAULT_RUNTIME_MAX_RETRIES
}

function readStoredMaxParallelSubAgents(): number {
  const stored = readStoredText(STORAGE_KEYS.maxParallelSubAgents)
  if (!stored) return DEFAULT_MAX_PARALLEL_SUB_AGENTS
  const value = Number(stored)
  return Number.isInteger(value) && value >= 1 ? value : DEFAULT_MAX_PARALLEL_SUB_AGENTS
}

function writeOrRemove(key: string, value: string): void {
  if (value) {
    writeStoredValue(key, value)
  } else {
    removeStoredValue(key)
  }
}

function writeStoredValue(key: string, value: string): void {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(key, value)
}

function removeStoredValue(key: string): void {
  if (typeof window === 'undefined') return
  window.localStorage.removeItem(key)
}
