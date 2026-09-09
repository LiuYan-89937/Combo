import type {
  ComputerUseActivityView,
  ComputerUseOperationView,
  RuntimeFrontendEvent,
  RuntimeViewState,
} from '@/types/protocol'
import { isComputerUseToolName } from '@/utils/computerUse'
import { toolPayloadValue } from './toolPayload'

type ComputerUseMutationState = Pick<RuntimeViewState, 'computerUseActivity'>

export function applyComputerUseLifecycleEvent(
  state: ComputerUseMutationState,
  event: RuntimeFrontendEvent,
  status: ComputerUseActivityView['status'],
): boolean {
  if (!eventBelongsToComputerUse(state, event)) return false
  const payload = event.payload || {}
  const progress = objectValue(payload.output)
  const current = state.computerUseActivity
  // Late output/cleanup from a revoked request must not replace a newer capsule.
  if (current.requestId && event.request_id && current.requestId !== event.request_id
    && status !== 'approval'
    && !['tool_call_proposed', 'tool_call_started'].includes(event.event_type)) return false
  const toolCallId = toolPayloadValue(payload, ['tool_call_id', 'toolCallId'])
  const retainsObservation = isSameComputerUseActivity(
    current,
    event.request_id || null,
    toolCallId ? String(toolCallId) : null,
  )
  const nextStatus = progress?.phase === 'cancelled'
    ? 'cancelled'
    : terminalComputerUseStatus(retainsObservation ? current.status : 'idle', status, event.event_type)
  const hasScreenshotField = hasOwn(progress, 'screenshot')
  const nextTarget = targetView(progress?.target)
  const sameTarget = retainsObservation && (!nextTarget
    || nextTarget.applicationId === current.target?.applicationId)
  const previousScreenshot = sameTarget ? current.screenshot : null
  const operations = retainsObservation ? [...(current.operations || [])] : []
  const operation = operationView(progress?.operation)
  if (operation) {
    const index = operations.findIndex(item => item.id === operation.id)
    if (index < 0) operations.push(operation)
    else operations[index] = operation
  }
  state.computerUseActivity = {
    operations,
    status: nextStatus,
    requestId: event.request_id || current.requestId || null,
    toolCallId: toolCallId ? String(toolCallId) : current.toolCallId || null,
    phase: phaseForEvent(event, progress, nextStatus),
    step: optionalNumber(progress?.step) ?? (retainsObservation ? current.step : null) ?? null,
    actionCount: optionalNumber(progress?.action_count)
      ?? (retainsObservation ? current.actionCount : null)
      ?? null,
    message: optionalText(progress?.message)
      || optionalText(payload.message)
      || (retainsObservation ? current.message : null)
      || null,
    startedAt: startedAtForEvent(current, event, retainsObservation),
    updatedAt: event.timestamp,
    target: nextTarget || (retainsObservation ? current.target : null) || null,
    accessibility: accessibilityView(progress?.accessibility)
      || (retainsObservation ? current.accessibility : null)
      || null,
    screenshot: hasScreenshotField
      ? screenshotView(progress?.screenshot) || previousScreenshot
      : previousScreenshot,
    screenshotError: hasOwn(progress, 'screenshot_error')
      ? optionalText(progress?.screenshot_error)
      : (retainsObservation ? current.screenshotError : null),
  }
  return true
}

function isSameComputerUseActivity(
  current: ComputerUseActivityView,
  requestId: string | null,
  toolCallId: string | null,
): boolean {
  if (!requestId || current.requestId !== requestId) return false
  if (!toolCallId || !current.toolCallId) return true
  return current.toolCallId === toolCallId
}

export function applyComputerUseApprovalRequest(
  state: ComputerUseMutationState,
  event: RuntimeFrontendEvent,
  request: Record<string, any>,
): boolean {
  if (!isComputerUsePayload(request)) return false
  return applyComputerUseLifecycleEvent(
    state,
    { ...event, payload: { ...(event.payload || {}), ...request } },
    'approval',
  )
}

export function resolveComputerUseApproval(
  state: ComputerUseMutationState,
  event: RuntimeFrontendEvent,
  toolCallIds: string[],
): void {
  const current = state.computerUseActivity
  if (current.status !== 'approval') return
  if (toolCallIds.length > 0 && current.toolCallId && !toolCallIds.includes(current.toolCallId)) return
  const approved = Boolean(event.payload?.approved)
  state.computerUseActivity = {
    ...current,
    status: approved ? 'running' : 'cancelled',
    phase: approved ? 'starting' : 'cancelled',
    updatedAt: event.timestamp,
  }
}

export function finalizeComputerUseForRequest(
  state: ComputerUseMutationState,
  requestId: string | null,
  timestamp: string,
  status: 'completed' | 'cancelled' | 'failed',
  message?: string,
): void {
  const current = state.computerUseActivity
  if (!requestId || current.requestId !== requestId) return
  if (current.status !== 'running' && current.status !== 'approval') return
  state.computerUseActivity = {
    ...current,
    status,
    phase: status,
    message: optionalText(message) || current.message || null,
    updatedAt: timestamp,
  }
}

function eventBelongsToComputerUse(
  state: ComputerUseMutationState,
  event: RuntimeFrontendEvent,
): boolean {
  if (isComputerUsePayload(event.payload || {})) return true
  const toolCallId = toolPayloadValue(event.payload || {}, ['tool_call_id', 'toolCallId'])
  return Boolean(
    toolCallId
    && state.computerUseActivity.toolCallId
    && String(toolCallId) === state.computerUseActivity.toolCallId,
  )
}

function isComputerUsePayload(payload: Record<string, any>): boolean {
  return ['tool_name', 'tool_id', 'name']
    .some(key => isComputerUseToolName(payload[key]))
}

function terminalComputerUseStatus(
  current: ComputerUseActivityView['status'],
  incoming: ComputerUseActivityView['status'],
  eventType: string,
): ComputerUseActivityView['status'] {
  if (['tool_observation_available', 'tool_call_output_delta'].includes(eventType)
    && ['completed', 'failed', 'cancelled'].includes(current)) {
    return current
  }
  return incoming
}

function phaseForEvent(
  event: RuntimeFrontendEvent,
  progress: Record<string, any> | null,
  status: ComputerUseActivityView['status'],
): string {
  const progressPhase = optionalText(progress?.phase)
  if (progressPhase) return progressPhase
  if (status === 'approval') return 'approval'
  if (status === 'completed' || status === 'failed' || status === 'cancelled') return status
  if (event.event_type === 'tool_call_proposed') return 'preparing'
  return 'starting'
}

function startedAtForEvent(
  current: ComputerUseActivityView,
  event: RuntimeFrontendEvent,
  retainsActivity: boolean,
): string | null {
  if (event.event_type === 'tool_call_started') return event.timestamp
  if (retainsActivity && current.startedAt) return current.startedAt
  if (event.event_type === 'tool_call_output_delta') return event.timestamp
  return null
}

function objectValue(value: unknown): Record<string, any> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, any>
    : null
}

function accessibilityView(value: unknown) {
  const accessibility = objectValue(value)
  if (!accessibility || typeof accessibility.text !== 'string') return null
  return {
    available: accessibility.available === true,
    application: optionalText(accessibility.application) || '',
    windowTitle: optionalText(accessibility.window_title) || '',
    error: optionalText(accessibility.error),
    text: accessibility.text,
  }
}

function screenshotView(value: unknown) {
  const screenshot = objectValue(value)
  if (!screenshot) return null
  const dataUrl = optionalText(screenshot.data_url)
  const width = optionalNumber(screenshot.width)
  const height = optionalNumber(screenshot.height)
  if (!dataUrl || width === null || width <= 0 || height === null || height <= 0) return null
  return { dataUrl, width, height }
}

function hasOwn(value: Record<string, any> | null, key: string): boolean {
  return Boolean(value && Object.prototype.hasOwnProperty.call(value, key))
}

function targetView(value: unknown) {
  const target = objectValue(value)
  if (!target) return null
  const applicationId = optionalText(target.application_id)
  const displayName = optionalText(target.display_name)
  const processId = optionalNumber(target.process_id)
  const windowId = optionalNumber(target.window_id)
  if (!applicationId || !displayName) return null
  const windowState = objectValue(target.window_state)
  return {
    applicationId,
    displayName,
    iconDataUrl: optionalText(target.icon_data_url),
    processId,
    windowId,
    windowTitle: optionalText(target.window_title) || '',
    windowState: {
      minimized: typeof windowState?.minimized === 'boolean' ? windowState.minimized : null,
      hidden: typeof windowState?.hidden === 'boolean' ? windowState.hidden : null,
      focused: typeof windowState?.focused === 'boolean' ? windowState.focused : null,
    },
  }
}

function optionalText(value: unknown): string | null {
  const text = String(value || '').trim()
  return text || null
}

function optionalNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function operationView(value: unknown): ComputerUseOperationView | null {
  const item = objectValue(value)
  if (!item || !item.id || !item.tool || !['running', 'returned', 'failed'].includes(String(item.status))) return null
  return {
    id: String(item.id), step: Number(item.step), tool: String(item.tool), app: String(item.app || ''),
    status: item.status as ComputerUseOperationView['status'],
    elementIndex: optionalText(item.element_index), x: optionalNumber(item.x), y: optionalNumber(item.y),
    textLength: optionalNumber(item.text_length), key: optionalText(item.key), action: optionalText(item.action),
    errorCode: optionalText(item.error_code), valueVerified: item.value_verified === true,
    inputVerification: optionalText(item.input_verification), inputMode: optionalText(item.input_mode),
  }
}
