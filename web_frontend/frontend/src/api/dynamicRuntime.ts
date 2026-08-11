import { backendUrl } from './backendUrl'

export const RUNTIME_PROTOCOL_VERSION = 'dynamic_runtime.v10'
export const RUNTIME_SCHEMA_VERSION = 'dynamic_runtime_schema.v10'

export type ExecutionPreference = 'auto' | 'react' | 'plan_and_execute'
export type ApprovalMode = 'ask' | 'auto' | 'always_approval'

export interface RuntimeDescriptor {
  protocol_version: string
  schema_version: string
  build_revision: string
}

export interface RuntimeConnection {
  descriptor: RuntimeDescriptor
  generation: number
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
}

export interface RuntimeEvent {
  event_id: string
  runtime_instance_id: string
  request_id: string
  session_id: string
  turn_id: string
  payload: { kind: string; [key: string]: unknown }
  created_at: string
}

export interface RuntimePolicy {
  principal_id: string
  policy_id: string
  revision: number
  execution_preference: ExecutionPreference
  approval_mode: ApprovalMode
  model_profile_id: string
  reasoning_intensity: number | null
  request_timeout_seconds: number
  max_model_attempts: number
  max_parallel_temporary_agents: number
  max_temporary_delegation_depth: number
  delegation_grant_ttl_seconds: number
  timezone: string
}

const PRINCIPAL_STORAGE_KEY = 'agentfactory.principal_id'
const CLIENT_STORAGE_KEY = 'agentfactory.client_instance_id'

export async function connectRuntime(): Promise<RuntimeConnection> {
  const principalId = stableId(PRINCIPAL_STORAGE_KEY)
  const clientInstanceId = stableId(CLIENT_STORAGE_KEY)
  const health = await rawRequest<{ status: string; protocol: RuntimeDescriptor; generation: number }>('/health')
  if (
    health.protocol.protocol_version !== RUNTIME_PROTOCOL_VERSION
    || health.protocol.schema_version !== RUNTIME_SCHEMA_VERSION
  ) {
    throw new Error('The frontend and dynamic runtime protocols are incompatible.')
  }
  const handshake = await rawRequest<{ status: string; generation: number }>('/api/runtime/handshake', {
    method: 'POST',
    body: JSON.stringify({ client_instance_id: clientInstanceId, client: health.protocol }),
  }, principalId)
  if (handshake.status !== 'accepted' || handshake.generation !== health.generation) {
    throw new Error('Dynamic runtime handshake was rejected.')
  }
  return { descriptor: health.protocol, generation: health.generation, clientInstanceId, principalId }
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
  policy: (connection: RuntimeConnection) =>
    request<RuntimePolicy>(connection, '/api/runtime/policy'),
  savePolicy: (connection: RuntimeConnection, payload: Record<string, unknown>) =>
    request<RuntimePolicy>(connection, '/api/runtime/policy', {
      method: 'PUT', body: JSON.stringify(payload),
    }),
  submitMessage: (connection: RuntimeConnection, sessionId: string, content: string) => {
    const commandId = crypto.randomUUID().replaceAll('-', '')
    return request<Record<string, unknown>>(connection, '/api/runtime/commands', {
      method: 'POST',
      body: JSON.stringify({
        protocol_version: connection.descriptor.protocol_version,
        command_id: commandId,
        client_instance_id: connection.clientInstanceId,
        principal_id: connection.principalId,
        session_id: sessionId,
        payload: {
          kind: 'send_message',
          message_id: crypto.randomUUID().replaceAll('-', ''),
          content,
        },
      }),
    })
  },
  streamEvents: (
    connection: RuntimeConnection,
    sessionId: string,
    afterEventId: string | null,
    onEvent: (event: RuntimeEvent) => void,
    signal: AbortSignal,
  ) => streamEvents(connection, sessionId, afterEventId, onEvent, signal),
}

async function request<T>(connection: RuntimeConnection, path: string, init: RequestInit = {}): Promise<T> {
  return rawRequest<T>(path, {
    ...init,
    headers: {
      'X-AgentFactory-Protocol': connection.descriptor.protocol_version,
      'X-AgentFactory-Schema': connection.descriptor.schema_version,
      'X-AgentFactory-Build': connection.descriptor.build_revision,
      'X-AgentFactory-Generation': String(connection.generation),
      ...(init.headers || {}),
    },
  }, connection.principalId)
}

async function rawRequest<T>(path: string, init: RequestInit = {}, principalId?: string): Promise<T> {
  const response = await fetch(await backendUrl(path), {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(principalId ? { 'X-AgentFactory-Principal': principalId } : {}),
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
      'X-AgentFactory-Principal': connection.principalId,
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

function stableId(key: string): string {
  const current = window.localStorage.getItem(key)?.trim()
  if (current) return current
  const value = crypto.randomUUID().replaceAll('-', '')
  window.localStorage.setItem(key, value)
  return value
}
