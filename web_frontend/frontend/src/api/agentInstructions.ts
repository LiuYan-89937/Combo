import { requestJson } from './http'

export interface AgentInstructionsView {
  content: string
  digest: string
}

export const agentInstructionsApi = {
  read: () => requestJson<AgentInstructionsView>('/api/agent/instructions'),
  replace: (content: string, expectedDigest: string) =>
    requestJson<AgentInstructionsView>('/api/agent/instructions', {
      method: 'PUT',
      body: JSON.stringify({ content, expected_digest: expectedDigest }),
    }),
}
