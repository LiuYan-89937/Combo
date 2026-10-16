import { requestJson, withQuery } from './http'

export interface AgentInstructionsView {
  content: string
  digest: string
  workspace_id: string
  revision: number
}

export const agentInstructionsApi = {
  read: (workspaceId: string) => requestJson<AgentInstructionsView>(withQuery('/api/agent/instructions', { workspace_id: workspaceId })),
  legacyDraft: () => requestJson<{ content: string }>('/api/agent/instructions/legacy-draft'),
  replace: (workspaceId: string, content: string, expectedDigest: string) =>
    requestJson<AgentInstructionsView>('/api/agent/instructions', {
      method: 'PUT',
      body: JSON.stringify({ workspace_id: workspaceId, content, expected_digest: expectedDigest }),
    }),
}
