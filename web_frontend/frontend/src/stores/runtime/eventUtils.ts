import type { FactoryFrontendEvent } from '@/types/protocol'

const REQUEST_SCOPED_PREFIXES = [
  'run_',
  'node_',
  'stage_',
  'model_',
  'tool_',
  'plan_',
  'context_',
  'interrupt_',
  'runtime_paused',
  'runtime_resumed',
]

const USER_INPUT_INTERRUPT_TYPES = new Set([
  'create_agent_question',
  'create_agent_publish_confirmation',
])

const DEDICATED_INTERRUPT_PANEL_TYPES = new Set([
  'create_agent_publish_confirmation',
])

export function isRequestScopedEvent(eventType: string): boolean {
  return REQUEST_SCOPED_PREFIXES.some((prefix) => eventType.startsWith(prefix))
}

export function isSchedulerRequest(requestId: string | null | undefined): boolean {
  return typeof requestId === 'string' && requestId.startsWith('scheduler-')
}

export function isBackgroundEvent(
  event: FactoryFrontendEvent,
  activeRequestId: string | null,
): boolean {
  return Boolean(
    event.request_id &&
    event.request_id !== activeRequestId &&
    isSchedulerRequest(event.request_id),
  )
}

export function interruptType(event: FactoryFrontendEvent | null): string {
  return String(event?.payload?.type || '')
}

export function isUserInputInterrupt(event: FactoryFrontendEvent | null): boolean {
  return USER_INPUT_INTERRUPT_TYPES.has(interruptType(event))
}

export function shouldRenderInterruptMessage(event: FactoryFrontendEvent): boolean {
  return !DEDICATED_INTERRUPT_PANEL_TYPES.has(interruptType(event))
}

export function interruptMessage(event: FactoryFrontendEvent): string {
  return String(event.payload?.message || event.message || '').trim()
}
