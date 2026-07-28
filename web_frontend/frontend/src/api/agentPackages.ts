import { requestBlob, requestEvent, requestJson, withQuery } from './http'

interface RecentAgentSessionsResponse {
  sessions: any[]
}

interface AgentPackageConfigurationResponse {
  package: any
}

export interface AgentPackageResourceDescriptorView {
  resource_id: string
  description: string
  required: boolean
  configured: boolean
  value?: unknown
  secret_fields: string[]
  used_by: string[]
  sandbox_access_expectation: string
  value_schema: Record<string, unknown>
  key_available: boolean
}

export interface AgentPackageResourcesResponse {
  package_id: string
  key_available: boolean
  resources: AgentPackageResourceDescriptorView[]
  migration: { status: string; migrated?: boolean; reason?: string }
}

export const agentPackagesApi = {
  list: () => requestEvent('/api/agent-packages'),
  select: (packageId: string, purpose?: 'run' | 'evolution') =>
    requestEvent('/api/agent-packages/select', {
      method: 'POST',
      body: JSON.stringify({ package_id: packageId, purpose }),
    }),
  instances: () => requestEvent('/api/agent-packages/instances'),
  recentSessions: (limit = 5) =>
    requestJson<RecentAgentSessionsResponse>(withQuery('/api/agent-packages/recent-sessions', { limit })),
  initialize: (packageId: string) =>
    requestEvent(`/api/agent-packages/${encodeURIComponent(packageId)}/initialize`, { method: 'POST' }),
  shutdown: (packageId: string) =>
    requestEvent(`/api/agent-packages/${encodeURIComponent(packageId)}/shutdown`, { method: 'POST' }),
  delete: (packageId: string) =>
    requestEvent(`/api/agent-packages/${encodeURIComponent(packageId)}`, { method: 'DELETE' }),
  exportArchive: (packageId: string) =>
    requestBlob(`/api/agent-packages/${encodeURIComponent(packageId)}/export`),
  updateToolDescription: (
    packageId: string,
    toolKind: 'model_tool' | 'package_tool',
    toolId: string,
    description: string,
  ) =>
    requestJson<AgentPackageConfigurationResponse>(
      `/api/agent-packages/${encodeURIComponent(packageId)}/tool-descriptions/${toolKind}/${encodeURIComponent(toolId)}`,
      {
        method: 'PATCH',
        body: JSON.stringify({ description }),
      },
    ),
  updateContextConfig: (packageId: string, config: Record<string, unknown>) =>
    requestJson<AgentPackageConfigurationResponse>(
      `/api/agent-packages/${encodeURIComponent(packageId)}/context-config`,
      {
        method: 'PATCH',
        body: JSON.stringify({ config }),
      },
    ),
  updateSchedulerConfig: (packageId: string, config: Record<string, unknown>) =>
    requestJson<AgentPackageConfigurationResponse>(
      `/api/agent-packages/${encodeURIComponent(packageId)}/scheduler-config`,
      {
        method: 'PATCH',
        body: JSON.stringify({ config }),
      },
    ),
  updateModelOverrides: (
    packageId: string,
    bindings: Record<string, Record<string, number | null>>,
    toolBindings: Record<string, Record<string, number | null>>,
  ) =>
    requestJson<AgentPackageConfigurationResponse>(
      `/api/agent-packages/${encodeURIComponent(packageId)}/model-overrides`,
      {
        method: 'PATCH',
        body: JSON.stringify({ bindings, tool_bindings: toolBindings }),
      },
    ),
  resources: (packageId: string) =>
    requestJson<AgentPackageResourcesResponse>(`/api/agent-packages/${encodeURIComponent(packageId)}/resources`),
  putResource: (packageId: string, resourceId: string, value: unknown) =>
    requestJson(`/api/agent-packages/${encodeURIComponent(packageId)}/resources/${encodeURIComponent(resourceId)}`, {
      method: 'PUT',
      body: JSON.stringify({ value }),
    }),
  deleteResource: (packageId: string, resourceId: string) =>
    requestJson(`/api/agent-packages/${encodeURIComponent(packageId)}/resources/${encodeURIComponent(resourceId)}`, {
      method: 'DELETE',
    }),
  sessions: (packageId: string) => requestEvent(`/api/agent-packages/${encodeURIComponent(packageId)}/sessions`),
  session: (packageId: string, sessionId: string) =>
    requestEvent(
      `/api/agent-packages/${encodeURIComponent(packageId)}/sessions/${encodeURIComponent(sessionId)}`
    ),
  deleteSession: (packageId: string, sessionId: string) =>
    requestEvent(
      `/api/agent-packages/${encodeURIComponent(packageId)}/sessions/${encodeURIComponent(sessionId)}`,
      { method: 'DELETE' }
    ),
}
