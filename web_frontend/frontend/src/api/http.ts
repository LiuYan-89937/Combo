import type { FactoryFrontendCommand, FactoryFrontendEvent } from '@/types/protocol'
import type {
  KnowledgeSourceInput,
  McpServerConfig,
  SchedulerJobInput,
  WorkspaceScope,
} from './commands'

interface EventResponse {
  event: FactoryFrontendEvent
}

interface CommandResponse {
  accepted: boolean
  command: FactoryFrontendCommand
}

export async function postCommand(command: FactoryFrontendCommand): Promise<CommandResponse> {
  return requestJson<CommandResponse>('/api/commands', {
    method: 'POST',
    body: JSON.stringify({ command }),
  })
}

export const agentPackagesApi = {
  list: () => requestEvent('/api/agent-packages'),
  select: (packageId: string, purpose?: 'run' | 'evolution') =>
    requestEvent('/api/agent-packages/select', {
      method: 'POST',
      body: JSON.stringify({ package_id: packageId, purpose }),
    }),
  sessions: (packageId: string) => requestEvent(`/api/agent-packages/${encodeURIComponent(packageId)}/sessions`),
  session: (packageId: string, sessionId: string) =>
    requestEvent(
      `/api/agent-packages/${encodeURIComponent(packageId)}/sessions/${encodeURIComponent(sessionId)}`
    ),
}

export const workspaceApi = {
  roots: (packageId?: string) => requestEvent(withQuery('/api/workspace/roots', { package_id: packageId })),
  entries: (scope: WorkspaceScope, path: string, packageId?: string) =>
    requestEvent(withQuery('/api/workspace/entries', { scope, path, package_id: packageId })),
  file: (scope: WorkspaceScope, path: string, packageId?: string) =>
    requestEvent(withQuery('/api/workspace/file', { scope, path, package_id: packageId })),
}

export const knowledgeApi = {
  sources: (packageId?: string) => requestEvent(withQuery('/api/knowledge/sources', { package_id: packageId })),
  addSource: (source: KnowledgeSourceInput, packageId?: string) =>
    requestEvent('/api/knowledge/sources', {
      method: 'POST',
      body: JSON.stringify({ source, package_id: packageId }),
    }),
  search: (query: string, sourceId?: string, packageId?: string) =>
    requestEvent(withQuery('/api/knowledge/search', { query, source_id: sourceId, package_id: packageId })),
}

export const extensionsApi = {
  list: (packageId?: string) => requestEvent(withQuery('/api/extensions', { package_id: packageId })),
  saveMcp: (server: McpServerConfig, packageId?: string) =>
    requestEvent('/api/extensions/mcp', {
      method: 'POST',
      body: JSON.stringify({ server, package_id: packageId }),
    }),
  testMcp: (serverIdOrConfig: string | McpServerConfig, packageId?: string) => {
    const payload =
      typeof serverIdOrConfig === 'string'
        ? { server_id: serverIdOrConfig, package_id: packageId }
        : { server: serverIdOrConfig, package_id: packageId }
    return requestEvent('/api/extensions/mcp/test', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },
  setMcpEnabled: (serverId: string, enabled: boolean) =>
    requestEvent(`/api/extensions/mcp/${encodeURIComponent(serverId)}`, {
      method: 'PATCH',
      body: JSON.stringify({ enabled }),
    }),
  setSkillEnabled: (skillId: string, enabled: boolean) =>
    requestEvent(`/api/extensions/skills/${encodeURIComponent(skillId)}`, {
      method: 'PATCH',
      body: JSON.stringify({ enabled }),
    }),
}

export const schedulerApi = {
  jobs: () => requestEvent('/api/scheduler/jobs'),
  createJob: (job: SchedulerJobInput) =>
    requestEvent('/api/scheduler/jobs', {
      method: 'POST',
      body: JSON.stringify({ job }),
    }),
  pause: (jobId: string) =>
    requestEvent(`/api/scheduler/jobs/${encodeURIComponent(jobId)}/pause`, { method: 'POST' }),
  resume: (jobId: string) =>
    requestEvent(`/api/scheduler/jobs/${encodeURIComponent(jobId)}/resume`, { method: 'POST' }),
  delete: (jobId: string) =>
    requestEvent(`/api/scheduler/jobs/${encodeURIComponent(jobId)}`, { method: 'DELETE' }),
  runNow: (jobId: string) =>
    requestJson<CommandResponse>(`/api/scheduler/jobs/${encodeURIComponent(jobId)}/run`, { method: 'POST' }),
}

async function requestEvent(url: string, init: RequestInit = {}): Promise<FactoryFrontendEvent> {
  const response = await requestJson<EventResponse>(url, init)
  return response.event
}

async function requestJson<T>(url: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init.headers || {}),
    },
  })
  if (!response.ok) {
    const text = await response.text()
    throw new Error(text || `HTTP ${response.status}`)
  }
  return response.json() as Promise<T>
}

function withQuery(path: string, params: Record<string, string | number | undefined | null>): string {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      search.set(key, String(value))
    }
  })
  const query = search.toString()
  return query ? `${path}?${query}` : path
}
