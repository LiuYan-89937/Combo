import { requestJson } from './http'

export const createAgentApi = {
  putResource: (sessionId: string, resourceId: string, value: unknown) =>
    requestJson(`/api/create-agent/sessions/${encodeURIComponent(sessionId)}/resources/${encodeURIComponent(resourceId)}`, {
      method: 'PUT',
      body: JSON.stringify({ value }),
    }),
}
