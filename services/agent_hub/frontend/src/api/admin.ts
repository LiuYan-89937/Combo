import { request } from './client'
import type { AgentRelease } from './types'

export function listPendingAgentReleases(limit = 100): Promise<AgentRelease[]> {
  return request<AgentRelease[]>('/admin/releases/pending', { query: { limit } })
}

export function listPublishedAgentReleases(limit = 100): Promise<AgentRelease[]> {
  return request<AgentRelease[]>('/admin/releases/published', { query: { limit } })
}

export function approveAgentRelease(
  releaseId: string,
  message = '',
): Promise<AgentRelease> {
  return request<AgentRelease>(
    `/admin/releases/${encodeURIComponent(releaseId)}/approve`,
    { method: 'POST', body: { message } },
  )
}

export function rejectAgentRelease(
  releaseId: string,
  message: string,
): Promise<{ release_id: string; status: string; message: string }> {
  return request(
    `/admin/releases/${encodeURIComponent(releaseId)}/reject`,
    { method: 'POST', body: { message } },
  )
}

export function unpublishAgentRelease(
  releaseId: string,
  message = '',
): Promise<AgentRelease> {
  return request<AgentRelease>(
    `/admin/releases/${encodeURIComponent(releaseId)}/unpublish`,
    { method: 'POST', body: { message } },
  )
}
