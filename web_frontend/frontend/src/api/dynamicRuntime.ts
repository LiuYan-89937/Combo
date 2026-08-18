import { backendUrl } from './backendUrl'
import { runtimeLocale } from '@/i18n'
import { runtimeClientInstanceId, runtimePrincipalId } from './runtimeIdentity'

export const RUNTIME_PROTOCOL_VERSION = 'dynamic_runtime.v14'
export const RUNTIME_SCHEMA_VERSION = 'dynamic_runtime_schema.v13'

export type ExecutionPreference = 'react' | 'plan_and_execute'
export type ApprovalMode = 'ask' | 'auto' | 'always_approval'

export interface RuntimeDescriptor {
  protocol_version: string
  schema_version: string
  build_revision: string
}

export interface RuntimeConnection {
  descriptor: RuntimeDescriptor
  clientInstanceId: string
  principalId: string
}

export interface ConversationSummary {
  session_id: string
  principal_id: string
  workspace_id: string
  title: string
  revision: number
  status: string
  created_at?: string
  updated_at?: string
}

export interface ConversationPart {
  kind: string
  [key: string]: unknown
}

export interface ConversationMessage {
  message_id: string
  session_id: string
  turn_id: string
  role: 'user' | 'assistant' | 'tool'
  status: 'pending' | 'committed' | 'cancelled'
  parts: ConversationPart[]
  created_at: string
  committed_at: string | null
  completion_reason?: 'user_interrupted' | null
}

export interface RuntimeEvent {
  event_id: string
  stream_id: string
  sequence: number
  session_sequence: number
  runtime_instance_id: string
  request_id: string
  session_id: string
  turn_id: string
  workspace_id: string
  task_revision: number
  attempt_id: string | null
  payload: { kind: string; [key: string]: unknown }
  created_at: string
}

export interface RuntimePolicy {
  principal_id: string
  policy_id: string
  revision: number
  execution_preference: ExecutionPreference
  approval_mode: ApprovalMode
  model_profile_id: string | null
  reasoning_intensity: number | null
  request_timeout_seconds: number
  max_model_attempts: number
  max_parallel_temporary_agents: number
  max_temporary_delegation_depth: number
  delegation_grant_ttl_seconds: number
  locale: 'zh-CN' | 'en-US'
  timezone: string
}

interface CommandReceipt {
  command_id: string
  request_id: string | null
  runtime_instance_id: string | null
  status: string
}

export async function connectRuntime(): Promise<RuntimeConnection> {
  const principalId = runtimePrincipalId()
  const clientInstanceId = runtimeClientInstanceId()
  const health = await rawRequest<{ status: string; protocol: RuntimeDescriptor }>('/health')
  if (
    health.protocol.protocol_version !== RUNTIME_PROTOCOL_VERSION
    || health.protocol.schema_version !== RUNTIME_SCHEMA_VERSION
  ) {
    throw new Error('The frontend and dynamic runtime protocols are incompatible.')
  }
  const handshake = await rawRequest<{ status: string }>('/api/runtime/handshake', {
    method: 'POST',
    body: JSON.stringify({ client_instance_id: clientInstanceId, client: health.protocol }),
  }, principalId)
  if (handshake.status !== 'accepted') {
    throw new Error('Dynamic runtime handshake was rejected.')
  }
  return { descriptor: health.protocol, clientInstanceId, principalId }
}

export const dynamicRuntimeApi = {
  listConversations: (connection: RuntimeConnection) =>
    request<{ conversations: ConversationSummary[] }>(connection, '/api/runtime/conversations'),
  createConversation: (connection: RuntimeConnection, title: string) =>
    request<{ conversation: ConversationSummary; title: string }>(connection, '/api/runtime/conversations', {
      method: 'POST', body: JSON.stringify({ title }),
    }),
  conversation: (connection: RuntimeConnection, sessionId: string) =>
    request<{ conversation: ConversationSummary; messages: ConversationMessage[] }>(
      connection,
      `/api/runtime/conversations/${encodeURIComponent(sessionId)}`,
    ),
  policy: (connection: RuntimeConnection) => request<RuntimePolicy>(connection, '/api/runtime/policy'),
  savePolicy: (connection: RuntimeConnection, payload: Record<string, unknown>) =>
    request<RuntimePolicy>(connection, '/api/runtime/policy', {
      method: 'PUT', body: JSON.stringify(payload),
    }),
  submitMessage: (connection: RuntimeConnection, sessionId: string, content: string) =>
    submitCommand(connection, sessionId, {
      kind: 'send_message',
      message_id: randomId(),
      content,
    }),
  cancelRuntime: (
    connection: RuntimeConnection,
    sessionId: string,
    runtimeInstanceId: string,
    requestId: string,
  ) => submitCommand(connection, sessionId, {
    kind: 'cancel_runtime_request',
    runtime_instance_id: runtimeInstanceId,
    request_id: requestId,
    reason: 'user_cancelled',
  }),
  streamEvents: (
    connection: RuntimeConnection,
    sessionId: string,
    afterEventId: string | null,
    onEvent: (event: RuntimeEvent) => void,
    signal: AbortSignal,
  ) => streamEvents(connection, sessionId, afterEventId, onEvent, signal),
}

function submitCommand(
  connection: RuntimeConnection,
  sessionId: string,
  payload: Record<string, unknown>,
): Promise<CommandReceipt> {
  return request<CommandReceipt>(connection, '/api/runtime/commands', {
    method: 'POST',
    body: JSON.stringify({
      protocol_version: connection.descriptor.protocol_version,
      command_id: randomId(),
      client_instance_id: connection.clientInstanceId,
      principal_id: connection.principalId,
      session_id: sessionId,
      payload,
    }),
  })
}

async function request<T>(connection: RuntimeConnection, path: string, init: RequestInit = {}): Promise<T> {
  return rawRequest<T>(path, {
    ...init,
    headers: {
      'X-Combo-Protocol': connection.descriptor.protocol_version,
      'X-Combo-Schema': connection.descriptor.schema_version,
      'X-Combo-Build': connection.descriptor.build_revision,
      ...(init.headers || {}),
    },
  }, connection.principalId)
}

async function rawRequest<T>(path: string, init: RequestInit = {}, principalId?: string): Promise<T> {
  const response = await fetch(await backendUrl(path), {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(principalId ? { 'X-Combo-Principal': principalId } : {}),
      'X-Combo-Locale': runtimeLocale(),
      ...(init.headers || {}),
    },
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: unknown } | null
    const detail = payload?.detail
    const error = new Error(typeof detail === 'string' ? detail : `HTTP ${response.status}`)
    Object.assign(error, { status: response.status, detail })
    throw error
  }
  return response.json() as Promise<T>
}

async function streamEvents(
  connection: RuntimeConnection,
  sessionId: string,
  afterEventId: string | null,
  onEvent: (event: RuntimeEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const url = new URL(await backendUrl('/api/runtime/events'), window.location.href)
  url.searchParams.set('session_id', sessionId)
  const response = await fetch(url, {
    signal,
    headers: {
      'X-Combo-Principal': connection.principalId,
      ...(afterEventId ? { 'Last-Event-ID': afterEventId } : {}),
    },
  })
  if (!response.ok || !response.body) throw new Error(`Runtime event stream failed: HTTP ${response.status}`)
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  while (true) {
    const { value, done } = await reader.read()
    if (done) return
    buffer += value
    let boundary = buffer.indexOf('\n\n')
    while (boundary >= 0) {
      const frame = buffer.slice(0, boundary)
      buffer = buffer.slice(boundary + 2)
      const event = parseRuntimeEvent(frame)
      if (event) onEvent(event)
      boundary = buffer.indexOf('\n\n')
    }
  }
}

function parseRuntimeEvent(frame: string): RuntimeEvent | null {
  if (!frame.includes('event: runtime_event')) return null
  const data = frame.split('\n').find(line => line.startsWith('data:'))?.slice(5).trim()
  return data ? JSON.parse(data) as RuntimeEvent : null
}

function randomId(): string {
  return crypto.randomUUID().replace(/-/g, '')
}
