import { postCommand } from '@/api/http'
import { applyRuntimeEvent, ensureRuntimeEventStream } from '@/composables/useEventStream'
import { useI18n } from '@/composables/useI18n'
import { useUiStore } from '@/stores/ui'
import { useRuntimeStore } from '@/stores/runtime'
import { useAgentStore } from '@/stores/agent'
import type { FactoryFrontendCommand, FactoryFrontendEvent } from '@/types/protocol'

const FOREGROUND_RUN_COMMANDS = new Set<FactoryFrontendCommand['type']>([
  'send_message',
  'resume_interrupt',
  'run_agent_package',
  'send_agent_package_message',
])

const SESSION_ESTABLISHING_COMMANDS = new Set<FactoryFrontendCommand['type']>([
  'send_message',
  'run_agent_package',
  'send_agent_package_message',
])

let cancellationBarrier: Promise<void> = Promise.resolve()

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

  function sendRuntimeCommand(command: FactoryFrontendCommand) {
    const dispatch = () => postCommand(command)
    const request = command.type !== 'cancel_runtime_request' && FOREGROUND_RUN_COMMANDS.has(command.type)
      ? cancellationBarrier.then(dispatch)
      : dispatch()
    if (command.type === 'cancel_runtime_request') {
      cancellationBarrier = request.then(() => undefined, () => undefined)
    }
    void request.then((response) => {
      const sessionId = String(response.receipt?.session_id || '').trim()
      const packageId = String(command.payload?.package_id || '').trim()
      if (sessionId && packageId && SESSION_ESTABLISHING_COMMANDS.has(command.type)) {
        runtimeStore.acceptAgentPackageSession(packageId, sessionId)
        agentStore.enterAgentChat(packageId, sessionId)
      }
      ensureRuntimeEventStream(response.event_stream_id)
    })
    void request.catch(reportError)
    return request
  }

  async function applyEventRequest(request: Promise<FactoryFrontendEvent>) {
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
