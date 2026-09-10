import type { SchedulerRunEventView } from '@/api/resourceTypes'

export type SchedulerActivityTranslator = (key: string) => string

export function schedulerActivity(
  event: SchedulerRunEventView,
  translate: SchedulerActivityTranslator,
): Record<string, unknown> | null {
  const payload = event.payload || {}
  if (event.event_type === 'tool_activity') {
    const details = recordValue(payload.details) || payload
    const rawEventType = String(details.event_type || '').trim()
    const toolCallId = String(details.tool_call_id || details.tool_id || '').trim()
    const status = toolActivityStatus(rawEventType, details.status)
    const toolName = String(details.model_alias || details.tool_name || details.tool_id || '').trim()
    return {
      phase_id: String(payload.phase_id || (toolCallId ? `tool:${toolCallId}` : `scheduler:${event.sequence}`)),
      category: 'tool',
      title: String(payload.title || toolName || translate('scheduler.toolActivity')),
      summary: String(payload.summary || details.message || (toolName ? `${toolName} ${status}` : translate('scheduler.toolActivity'))),
      status,
      occurred_at: event.created_at,
      details: { ...details, event_type: rawEventType || 'tool_activity' },
    }
  }
  if (['tool_proposed', 'tool_started', 'tool_completed', 'tool_failed', 'tool_cancelled', 'tool_call_proposed', 'tool_call_started', 'tool_call_completed', 'tool_call_failed', 'tool_call_cancelled', 'tool_contract_invalid', 'tool_observation_available'].includes(event.event_type)) {
    return toolEventActivity(event, translate)
  }
  const streamId = String(payload.stream_id || '').trim()
  if (event.event_type === 'model_stream_delta' || event.event_type === 'model_message_completed' || event.event_type === 'model_generation_interrupted') {
    return streamActivity(event, 'output', streamId, translate)
  }
  if (event.event_type === 'model_reasoning_delta' || event.event_type === 'model_reasoning_completed') {
    return streamActivity(event, 'reasoning', streamId, translate)
  }
  if (event.event_type === 'tool_output_delta' || event.event_type === 'tool_call_output_delta') {
    const toolCallId = String(payload.tool_call_id || payload.tool_id || '').trim()
    const toolName = String(payload.tool_name || payload.tool_id || '').trim()
    return {
      phase_id: toolCallId ? `tool:${toolCallId}` : `scheduler:${event.sequence}`,
      category: 'tool',
      title: String(toolName || translate('scheduler.toolActivity')),
      summary: String(payload.message || (toolName ? `${toolName} running` : translate('scheduler.toolActivity'))),
      status: 'running',
      occurred_at: event.created_at,
      details: { ...payload, event_type: 'tool_call_output_delta', status: 'running' },
    }
  }
  if (event.event_type === 'model_call_started') {
    return streamActivity(event, 'output', streamId, translate)
  }
  if (event.event_type === 'model_call_failed') {
    return streamActivity(event, 'output', streamId, translate)
  }
  if (event.event_type === 'process_output') {
    return processActivity(event, translate)
  }
  if (event.event_type === 'runtime_activity_updated') {
    const details = recordValue(payload.details) || payload
    const phase = String(details.plan_step_id || details.activity_id || details.source || 'runtime')
    const title = String(payload.title || details.title || '').trim()
    const summary = String(payload.summary || details.summary || '').trim()
    // Status-only heartbeats carry nothing worth a row.
    if (!title && !summary) return null
    return {
      phase_id: `runtime:${phase}`,
      category: 'activity',
      title: title || translate('scheduler.activity'),
      summary: summary || title,
      status: String(payload.status || details.status || 'running'),
      occurred_at: event.created_at,
      details: { ...details, scheduler_event_type: event.event_type },
    }
  }
  // Unmodelled runtime observations (node/context events) are persisted once per
  // emission. Most carry no text at all, and giving each its own row produced a
  // wall of identical entries, so keep only the ones with something to say and
  // collapse repeats of the same activity under one stable phase id.
  const content = String(payload.text || payload.message || payload.summary || '').trim()
  if (!content && !(event.event_type in EVENT_TITLES)) return null
  return {
    phase_id: `${event.event_type}:${activityIdentity(event, payload)}`,
    category: 'activity',
    title: eventTitle(event.event_type, translate),
    summary: content || eventSummary(event, translate),
    status: eventStatus(event.event_type),
    occurred_at: event.created_at,
    details: { ...payload, scheduler_event_type: event.event_type },
  }
}

function activityIdentity(event: SchedulerRunEventView, payload: Record<string, unknown>): string {
  const details = recordValue(payload.details) || payload
  const explicit = String(
    details.activity_id || details.plan_step_id || details.node_id
    || details.source_event_id || details.source
    || payload.activity_id || payload.node_id || payload.source || '',
  ).trim()
  return explicit || `seq:${event.sequence}`
}

function toolEventActivity(
  event: SchedulerRunEventView,
  translate: SchedulerActivityTranslator,
): Record<string, unknown> {
  const payload = event.payload || {}
  const toolCallId = String(payload.tool_call_id || payload.tool_id || '').trim()
  const eventType = event.event_type.startsWith('tool_call_') || event.event_type === 'tool_contract_invalid' || event.event_type === 'tool_observation_available'
    ? event.event_type
    : event.event_type === 'tool_proposed' ? 'tool_call_proposed' : event.event_type.replace('tool_', 'tool_call_')
  const status = toolActivityStatus(eventType, payload.status)
  const toolName = String(payload.tool_name || payload.tool_id || '').trim()
  return {
    phase_id: toolCallId ? `tool:${toolCallId}` : `scheduler:${event.sequence}`,
    category: 'tool',
    title: String(toolName || translate('scheduler.toolActivity')),
    summary: String(payload.message || payload.summary || (toolName ? `${toolName} ${status}` : translate('scheduler.toolActivity'))),
    status,
    occurred_at: event.created_at,
    details: { ...payload, event_type: eventType, status },
  }
}

function streamActivity(
  event: SchedulerRunEventView,
  streamKind: 'output' | 'reasoning',
  streamId: string,
  translate: SchedulerActivityTranslator,
): Record<string, unknown> {
  const payload = event.payload || {}
  const failed = event.event_type === 'model_call_failed'
    || event.event_type === 'model_generation_interrupted'
  const completed = failed || event.event_type.endsWith('_completed')
    || event.event_type === 'model_message_completed'
  return {
    phase_id: `model:${streamId || 'default'}:${streamKind}`,
    category: 'stream',
    title: streamKind === 'reasoning' ? translate('scheduler.modelReasoning') : translate('scheduler.modelOutput'),
    summary: String(payload.delta || payload.content || payload.error || translate(
      failed ? 'scheduler.status.failed' : completed ? 'scheduler.result' : 'scheduler.modelGenerating',
    )),
    status: failed ? 'failed' : completed ? 'completed' : 'running',
    occurred_at: event.created_at,
    stream_kind: streamKind,
    details: { ...payload, stream_id: streamId, stream_kind: streamKind },
  }
}

function processActivity(
  event: SchedulerRunEventView,
  translate: SchedulerActivityTranslator,
): Record<string, unknown> {
  const payload = event.payload || {}
  const stream = String(payload.stream || 'stdout').trim() || 'stdout'
  return {
    phase_id: `process:${stream}`,
    category: 'stream',
    title: translate('scheduler.output'),
    summary: String(payload.text || payload.stdout || payload.stderr || translate('scheduler.output')),
    status: 'running',
    occurred_at: event.created_at,
    stream_kind: 'output',
    stream_format: 'plain',
    details: { ...payload, stream_kind: 'output', stream_format: 'plain', delta: payload.text || payload.stdout || payload.stderr || '' },
  }
}

function toolActivityStatus(eventType: string, value: unknown): string {
  if (eventType === 'tool_call_failed' || eventType === 'tool_contract_invalid') return 'failed'
  if (eventType === 'tool_call_cancelled') return 'cancelled'
  if (eventType === 'tool_call_completed' || eventType === 'tool_observation_available') return 'completed'
  const status = String(value || '').trim()
  return status || 'running'
}

// Event types we have a dedicated label for. Anything else is an unmodelled
// runtime observation and only surfaces when it actually carries text.
const EVENT_TITLES: Record<string, string> = {
  run_started: 'scheduler.status.running',
  agent_queued: 'scheduler.agentQueued',
  process_started: 'scheduler.processStarted',
  process_output: 'scheduler.output',
  model_call_started: 'scheduler.modelGenerating',
  model_message_completed: 'scheduler.result',
  model_stream_delta: 'scheduler.modelOutput',
  model_reasoning_delta: 'scheduler.modelReasoning',
  model_reasoning_completed: 'scheduler.modelReasoning',
  result: 'scheduler.result',
  failed: 'scheduler.status.failed',
  cancelled: 'scheduler.status.cancelled',
}

function eventTitle(eventType: string, translate: SchedulerActivityTranslator): string {
  return EVENT_TITLES[eventType] ? translate(EVENT_TITLES[eventType]) : translate('scheduler.activity')
}

function eventSummary(event: SchedulerRunEventView, translate: SchedulerActivityTranslator): string {
  const payload = event.payload || {}
  return String(payload.text || payload.message || payload.summary || payload.stderr || payload.stdout || eventTitle(event.event_type, translate)).trim()
}

function eventStatus(eventType: string): string {
  if (eventType === 'failed') return 'failed'
  if (eventType === 'cancelled') return 'cancelled'
  if (eventType === 'result') return 'completed'
  return 'running'
}

function recordValue(value: unknown): Record<string, any> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, any>
    : null
}
