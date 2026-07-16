import { requestJson } from './http'

interface CreateAgentPublishResponse {
  published: Record<string, any>
}

export const createAgentApi = {
  publish: (sessionId: string, confirmation = '用户在 Web 界面点击发布') =>
    requestJson<CreateAgentPublishResponse>(
      `/api/create-agent/sessions/${encodeURIComponent(sessionId)}/publish`,
      {
        method: 'POST',
        body: JSON.stringify({ confirmation }),
      },
    ),
  putResource: (sessionId: string, resourceId: string, value: unknown) =>
    requestJson(`/api/create-agent/sessions/${encodeURIComponent(sessionId)}/resources/${encodeURIComponent(resourceId)}`, {
      method: 'PUT',
      body: JSON.stringify({ value }),
    }),
}
