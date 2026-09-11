import { postCommand } from '@/api/http'
import { applyRuntimeEvent, ensureRuntimeEventStream } from '@/composables/useEventStream'
import { useI18n } from '@/composables/useI18n'
import { useUiStore } from '@/stores/ui'
import { useRuntimeStore } from '@/stores/runtime'
import { useAgentStore } from '@/stores/agent'
import type { RuntimeFrontendCommand, RuntimeFrontendEvent } from '@/types/protocol'

const FOREGROUND_RUN_COMMANDS = new Set<RuntimeFrontendCommand['type']>([
  'send_message',
  'resume_interrupt',
  'run_agent_package',
  'send_agent_package_message',
])

const SESSION_ESTABLISHING_COMMANDS = new Set<RuntimeFrontendCommand['type']>([
  'send_message',
  'run_agent_package',
  'send_agent_package_message',
])

let cancellationBarrier: Promise<void> = Promise.resolve()
interface SubmissionLane {
  tail: Promise<void>
  sessionId: string | null
}
const submissionLanes = new Map<string, SubmissionLane>()

export function useCommandTransport() {
  const uiStore = useUiStore()
  const runtimeStore = useRuntimeStore()
  const agentStore = useAgentStore()
  const { t } = useI18n()

  function reportError(error: unknown) {
    const message = error instanceof Error ? error.message : String(error)
    console.error('Command failed:', error)
    uiStore.addNotification({
      type: 'error',
      title: t('common.error'),
      message,
      duration: 5000,
    })
  }

  function sendRuntimeCommand(
    command: RuntimeFrontendCommand,
    beforeDispatch?: (command: RuntimeFrontendCommand) => Promise<void>,
  ) {
    const ordered = FOREGROUND_RUN_COMMANDS.has(command.type)
    const scope = runtimeStore.activeConversationScope
    const sessionId = String(command.session_id || '').trim() || null
    const laneKey = sessionId ? `session:${sessionId}` : `scope:${scope}`
    const lane = ordered
      ? submissionLanes.get(laneKey) || { tail: Promise.resolve(), sessionId }
      : null
    if (lane) submissionLanes.set(laneKey, lane)
    const cancellation = cancellationBarrier
    const dispatch = async () => {
      if (lane) await cancellation
      if (lane?.sessionId && !command.session_id) {
        command.session_id = lane.sessionId
        command.payload = { ...command.payload, session_id: lane.sessionId }
      }
      await beforeDispatch?.(command)
      const response = await postCommand(command)
      runtimeStore.settleRequestSubmission(command.request_id, response.receipt.status !== 'rejected')
      const acceptedSessionId = String(response.receipt?.session_id || '').trim()
      const packageId = String(command.payload?.package_id || '').trim()
      if (acceptedSessionId && lane) {
        lane.sessionId = acceptedSessionId
        submissionLanes.set(`session:${acceptedSessionId}`, lane)
      }
      if (acceptedSessionId && packageId && SESSION_ESTABLISHING_COMMANDS.has(command.type)) {
        // A delayed response must not navigate away from a conversation the user switched to.
        if (runtimeStore.activeConversationScope === scope || runtimeStore.activeAgentSessionId === acceptedSessionId) {
          runtimeStore.acceptAgentPackageSession(packageId, acceptedSessionId)
          agentStore.enterAgentChat(packageId, acceptedSessionId)
        }
      }
      ensureRuntimeEventStream(response.event_stream_id)
      return response
    }
    // Register the submission synchronously, before Git/attachment preparation can yield.
    const request = lane ? lane.tail.then(dispatch) : dispatch()
    if (lane) {
      const tail = request.then(() => undefined, () => undefined)
      lane.tail = tail
      void tail.then(() => {
        if (lane.tail !== tail) return
        for (const [key, value] of submissionLanes) if (value === lane) submissionLanes.delete(key)
      })
    }
    if (command.type === 'cancel_runtime_request') {
      cancellationBarrier = request.then(() => undefined, () => undefined)
    }
    void request.catch(error => {
      runtimeStore.settleRequestSubmission(command.request_id, false)
      reportError(error)
    })
    return request
  }

  async function applyEventRequest(request: Promise<RuntimeFrontendEvent>) {
    try {
      const event = await request
      applyRuntimeEvent(event)
      return event
    } catch (error) {
      reportError(error)
      return null
    }
  }

  return {
    applyEventRequest,
    reportError,
    sendRuntimeCommand,
  }
}
