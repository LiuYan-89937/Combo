import { requestJson } from './http'

export interface ContextCompressionResult {
  status: 'completed' | 'skipped'
  reason?: string
  token_estimate_before?: number | null
  token_estimate_after?: number | null
  original_message_count?: number
  compressed_message_count?: number
  compacted_message_count?: number
  context_window?: Record<string, unknown>
}

export const contextCompressionApi = {
  compress: (sessionId: string) => requestJson<{ result: ContextCompressionResult }>(
    `/api/agent-packages/main_chat/sessions/${encodeURIComponent(sessionId)}/context/compress`,
    { method: 'POST', body: '{}' },
  ),
}
