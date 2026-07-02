import { postCommand } from '@/api/http'
import { applyRuntimeEvent } from '@/composables/useEventStream'
import { useI18n } from '@/composables/useI18n'
import { useUiStore } from '@/stores/ui'
import type { FactoryFrontendCommand, FactoryFrontendEvent } from '@/types/protocol'

export function useCommandTransport() {
  const uiStore = useUiStore()
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
    void postCommand(command).catch(reportError)
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
