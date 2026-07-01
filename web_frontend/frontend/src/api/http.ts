import type { FactoryFrontendCommand, FactoryFrontendEvent } from '@/types/protocol'
import type {
  KnowledgeSourceInput,
  McpServerConfig,
  SchedulerJobInput,
  SkillConfig,
  WorkspaceScope,
} from './commands'

interface EventResponse {
  event: FactoryFrontendEvent
}

interface CommandResponse {
  accepted: boolean
  command: FactoryFrontendCommand
}

export interface BlobResponse {
  blob: Blob
  filename: string | null
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
  instances: () => requestEvent('/api/agent-packages/instances'),
  initialize: (packageId: string) =>
    requestEvent(`/api/agent-packages/${encodeURIComponent(packageId)}/initialize`, { method: 'POST' }),
  shutdown: (packageId: string) =>
    requestEvent(`/api/agent-packages/${encodeURIComponent(packageId)}/shutdown`, { method: 'POST' }),
  delete: (packageId: string) =>
    requestEvent(`/api/agent-packages/${encodeURIComponent(packageId)}`, { method: 'DELETE' }),
  exportArchive: (packageId: string) =>
    requestBlob(`/api/agent-packages/${encodeURIComponent(packageId)}/export`),
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
  documents: (sourceId: string, packageId?: string) =>
    requestEvent(withQuery('/api/knowledge/documents', { source_id: sourceId, package_id: packageId })),
  search: (query: string, sourceId?: string, packageId?: string) =>
    requestEvent(withQuery('/api/knowledge/search', { query, source_id: sourceId, package_id: packageId })),
  removeSource: (sourceId: string, packageId?: string) =>
    requestEvent(withQuery(`/api/knowledge/sources/${encodeURIComponent(sourceId)}`, { package_id: packageId }), {
      method: 'DELETE',
    }),
  reindexSource: (sourceId: string, packageId?: string) =>
    requestEvent(withQuery(`/api/knowledge/sources/${encodeURIComponent(sourceId)}/reindex`, { package_id: packageId }), {
      method: 'POST',
    }),
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
  setMcpEnabled: (serverId: string, enabled: boolean, packageId?: string) =>
    requestEvent(`/api/extensions/mcp/${encodeURIComponent(serverId)}`, {
      method: 'PATCH',
      body: JSON.stringify({ enabled, package_id: packageId }),
    }),
  removeMcp: (serverId: string, packageId?: string) =>
    requestEvent(withQuery(`/api/extensions/mcp/${encodeURIComponent(serverId)}`, { package_id: packageId }), {
      method: 'DELETE',
    }),
  saveSkill: (skill: SkillConfig, packageId?: string) =>
    requestEvent('/api/extensions/skills', {
      method: 'POST',
      body: JSON.stringify({
        skill,
        replace_skill_id: skill.replace_skill_id,
        package_id: packageId,
      }),
    }),
  setSkillEnabled: (skillId: string, enabled: boolean, packageId?: string) =>
    requestEvent(`/api/extensions/skills/${encodeURIComponent(skillId)}`, {
      method: 'PATCH',
      body: JSON.stringify({ enabled, package_id: packageId }),
    }),
  removeSkill: (skillId: string, packageId?: string) =>
    requestEvent(withQuery(`/api/extensions/skills/${encodeURIComponent(skillId)}`, { package_id: packageId }), {
      method: 'DELETE',
    }),
}

export const schedulerApi = {
  options: (packageId?: string) => requestEvent(withQuery('/api/scheduler/options', { package_id: packageId })),
  jobs: (packageId?: string) => requestEvent(withQuery('/api/scheduler/jobs', { package_id: packageId })),
  createJob: (job: SchedulerJobInput, packageId?: string) =>
    requestEvent('/api/scheduler/jobs', {
      method: 'POST',
      body: JSON.stringify({ job, package_id: packageId }),
    }),
  pause: (jobId: string, packageId?: string) =>
    requestEvent(`/api/scheduler/jobs/${encodeURIComponent(jobId)}/pause`, {
      method: 'POST',
      body: JSON.stringify({ package_id: packageId }),
    }),
  resume: (jobId: string, packageId?: string) =>
    requestEvent(`/api/scheduler/jobs/${encodeURIComponent(jobId)}/resume`, {
      method: 'POST',
      body: JSON.stringify({ package_id: packageId }),
    }),
  delete: (jobId: string, packageId?: string) =>
    requestEvent(withQuery(`/api/scheduler/jobs/${encodeURIComponent(jobId)}`, { package_id: packageId }), {
      method: 'DELETE',
    }),
  runs: (jobId?: string, limit = 20, packageId?: string) =>
    requestEvent(withQuery('/api/scheduler/runs', { job_id: jobId, limit, package_id: packageId })),
  runNow: (jobId: string, packageId?: string) =>
    requestJson<CommandResponse>(`/api/scheduler/jobs/${encodeURIComponent(jobId)}/run`, {
      method: 'POST',
      body: JSON.stringify({ package_id: packageId }),
    }),
}

async function requestEvent(url: string, init: RequestInit = {}): Promise<FactoryFrontendEvent> {
  const response = await requestJson<EventResponse>(url, init)
  return response.event
}

async function requestBlob(url: string, init: RequestInit = {}): Promise<BlobResponse> {
  const response = await fetch(url, init)
  if (!response.ok) {
    const text = await response.text()
    throw new Error(text || `HTTP ${response.status}`)
  }
  return {
    blob: await response.blob(),
    filename: filenameFromDisposition(response.headers.get('content-disposition')),
  }
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

function filenameFromDisposition(disposition: string | null): string | null {
  if (!disposition) return null
  const utf8Match = disposition.match(/filename\*=UTF-8''([^;]+)/i)
  if (utf8Match?.[1]) return decodeURIComponent(utf8Match[1])
  const asciiMatch = disposition.match(/filename="?([^";]+)"?/i)
  return asciiMatch?.[1] || null
}
