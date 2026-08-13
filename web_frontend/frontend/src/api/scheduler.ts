import type { SchedulerJobInput, SchedulerRunEventView } from './resourceTypes'
import { requestEvent, requestJson, type CommandResponse, withQuery } from './http'

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
  runEvents: (runId: string, after = 0) =>
    requestJson<{ events: SchedulerRunEventView[] }>(withQuery(`/api/scheduler/runs/${encodeURIComponent(runId)}/events`, { after })),
  cancelRun: (runId: string) =>
    requestJson<{ run: Record<string, any> }>(`/api/scheduler/runs/${encodeURIComponent(runId)}/cancel`, { method: 'POST' }),
  resolveInteraction: (runId: string, interactionId: string, decision: 'approve' | 'reject' | 'trust' | 'answer' | 'revise', response?: string) =>
    requestJson<{ run: Record<string, any> }>(`/api/scheduler/runs/${encodeURIComponent(runId)}/interactions/${encodeURIComponent(interactionId)}`, {
      method: 'POST',
      body: JSON.stringify({ decision, response }),
    }),
}
