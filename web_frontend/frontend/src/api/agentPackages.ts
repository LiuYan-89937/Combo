import { requestBlob, requestEvent, requestJson, withQuery } from './http'

interface RecentAgentSessionsResponse {
  sessions: any[]
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
  sessions: (packageId: string) => requestEvent(`/api/agent-packages/${encodeURIComponent(packageId)}/sessions`),
  session: (packageId: string, sessionId: string) =>
    requestEvent(
      `/api/agent-packages/${encodeURIComponent(packageId)}/sessions/${encodeURIComponent(sessionId)}`
    ),
}
