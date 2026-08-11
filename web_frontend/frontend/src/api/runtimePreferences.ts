import { requestJson } from './http'
import type { ApprovalMode, ExecutionPreference } from './dynamicRuntime'

export interface RuntimePreferences {
  revision: number
  execution_preference: ExecutionPreference
  model_profile_id: string | null
  reasoning_intensity: number | null
  approval_mode: ApprovalMode
  request_timeout_seconds: number
  max_retries: number
  max_parallel_sub_agents: number
  updated_at: string | null
}

export type RuntimePreferencesPatch = Partial<Pick<
  RuntimePreferences,
  | 'model_profile_id'
  | 'execution_preference'
  | 'reasoning_intensity'
  | 'approval_mode'
  | 'request_timeout_seconds'
  | 'max_retries'
  | 'max_parallel_sub_agents'
>>

export const runtimePreferencesApi = {
  get: () => requestJson<RuntimePreferences>('/api/runtime/preferences'),
  update: (patch: RuntimePreferencesPatch, expectedRevision: number) =>
    requestJson<RuntimePreferences>('/api/runtime/preferences', {
      method: 'PATCH',
      body: JSON.stringify({ expected_revision: expectedRevision, ...patch }),
    }),
}
