/*
 * Upload state machine for the publish flow. Encapsulates the four-step OSS
 * direct-upload dance and terminal-aware polling so the view stays declarative.
 *
 *   1. createUpload(filename, size)  -> signed PUT request + upload record
 *   2. putToObjectStore(...)         -> raw bytes to OSS (signature preserved)
 *   3. completeUpload(id)            -> queue for validation
 *   4. poll fetchUpload(id)          -> until a terminal status
 *
 * Polling backs off, pauses while the tab is hidden, and stops on terminal
 * states so we never hammer the API in a background tab.
 */
import { computed, ref } from 'vue'
import { completeUpload, createUpload, fetchUpload, putToObjectStore } from '@/api/uploads'
import { ApiError, NetworkError } from '@/api/client'
import type { HubUpload, UploadStatus } from '@/api/types'

export type FlowPhase =
  | 'idle'
  | 'creating'
  | 'uploading'
  | 'finalizing'
  | 'tracking'
  | 'done'
  | 'error'

const TERMINAL: UploadStatus[] = ['published', 'rejected', 'failed']
const POLL_MS = 2500
const POLL_MAX_MS = 12_000

export function useUploadFlow() {
  const phase = ref<FlowPhase>('idle')
  const progress = ref(0) // 0..1 during the OSS PUT
  const upload = ref<HubUpload | null>(null)
  const errorMessage = ref('')
  const errorRequestId = ref<string | undefined>()

  let abort: AbortController | null = null
  let pollTimer: ReturnType<typeof setTimeout> | undefined
  let pollInterval = POLL_MS
  let visibilityBound = false

  const isTerminal = computed(() => (upload.value ? TERMINAL.includes(upload.value.status) : false))
  const isActive = computed(() =>
    ['creating', 'uploading', 'finalizing', 'tracking'].includes(phase.value),
  )

  function reset() {
    stopPolling()
    abort?.abort()
    abort = null
    phase.value = 'idle'
    progress.value = 0
    upload.value = null
    errorMessage.value = ''
    errorRequestId.value = undefined
  }

  function fail(error: unknown, fallback: string) {
    if (error instanceof ApiError) {
      errorMessage.value = error.message
      errorRequestId.value = error.requestId
    } else if (error instanceof NetworkError) {
      errorMessage.value = fallback
    } else if (error instanceof Error) {
      errorMessage.value = error.message || fallback
    } else {
      errorMessage.value = fallback
    }
    phase.value = 'error'
  }

  function stopPolling() {
    clearTimeout(pollTimer)
    pollTimer = undefined
  }

  function scheduleNextPoll(id: string) {
    stopPolling()
    if (document.visibilityState === 'hidden') return // resume on visibilitychange
    pollTimer = setTimeout(() => void pollOnce(id), pollInterval)
  }

  async function pollOnce(id: string) {
    try {
      const next = await fetchUpload(id)
      upload.value = next
      if (TERMINAL.includes(next.status)) {
        phase.value = 'done'
        stopPolling()
        return
      }
      pollInterval = Math.min(Math.round(pollInterval * 1.25), POLL_MAX_MS)
      scheduleNextPoll(id)
    } catch (error) {
      // Transient poll failure: keep the last known state and retry with backoff.
      pollInterval = Math.min(Math.round(pollInterval * 1.5), POLL_MAX_MS)
      scheduleNextPoll(id)
      void error
    }
  }

  function bindVisibility(id: string) {
    if (visibilityBound) return
    visibilityBound = true
    document.addEventListener('visibilitychange', () => {
      if (
        document.visibilityState === 'visible' &&
        upload.value &&
        !TERMINAL.includes(upload.value.status)
      ) {
        pollInterval = POLL_MS
        void pollOnce(id)
      }
    })
  }

  async function start(file: File) {
    reset()
    abort = new AbortController()
    try {
      phase.value = 'creating'
      const created = await createUpload(file.name, file.size)
      upload.value = created.upload

      phase.value = 'uploading'
      progress.value = 0
      await putToObjectStore(created.upload_request, file, {
        signal: abort.signal,
        onProgress: ({ loaded, total }) => {
          progress.value = total > 0 ? loaded / total : 0
        },
      })

      phase.value = 'finalizing'
      const finalized = await completeUpload(created.upload.upload_id)
      upload.value = finalized

      if (TERMINAL.includes(finalized.status)) {
        phase.value = 'done'
        return
      }

      phase.value = 'tracking'
      pollInterval = POLL_MS
      bindVisibility(finalized.upload_id)
      scheduleNextPoll(finalized.upload_id)
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        reset()
        return
      }
      fail(error, 'upload failed')
    }
  }

  function cancel() {
    abort?.abort()
    reset()
  }

  return {
    phase,
    progress,
    upload,
    errorMessage,
    errorRequestId,
    isTerminal,
    isActive,
    start,
    cancel,
    reset,
  }
}
