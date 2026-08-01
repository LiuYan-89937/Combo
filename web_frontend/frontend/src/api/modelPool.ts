import { requestJson, withQuery } from './http'

export type ModelUsageGroupBy = 'model' | 'provider' | 'agent'
export type ModelRole = 'main' | 'task' | 'compression' | 'embedding'
export type ModelRoleBindings = Record<ModelRole, string | null>
export interface ModelPoolDefaults {
  context_window_tokens: number
  compression_trigger_tokens: number
}

export interface ModelProviderProfile {
  provider_id: string
  display_name: string
  kind: 'chat' | 'embedding' | 'image_generation'
  supported_kinds?: Array<'chat' | 'embedding' | 'image_generation'>
  adapter_id: string
  transport: string
  default_base_url?: string
  content_parts?: Record<string, string>
  tools?: Record<string, string>
  structured_output_methods?: string[]
  default_structured_output_method?: string
  reasoning?: Record<string, unknown>
  cache_usage?: string
  capabilities?: Record<string, unknown>
  notes: string[]
}

export interface ModelPoolCredential {
  credential_id: string
  display_name: string
  provider: string
  base_url: string
  api_key_masked: string
  api_key_fingerprint: string
  has_api_key: boolean
  enabled: boolean
  created_at: string
  updated_at: string
}

export interface ModelPoolProfile {
  profile_id: string
  display_name: string
  description: string
  kind: 'chat' | 'embedding' | 'image_generation'
  provider: string
  credential_id: string
  model_name: string
  embedding_dimensions?: number | null
  enabled: boolean
  capabilities: {
    input_modalities: string[]
    output_modalities: string[]
    tool_calling: boolean
    streaming_tool_calls: boolean
    strict_tool_schema: boolean
    structured_output_methods: string[]
    reasoning_supported: boolean
    reasoning_efforts: string[]
    reasoning_content: boolean
    cache_usage: boolean
    text_to_image?: boolean
    image_to_image?: boolean
    image_edit?: boolean
    multi_image_reference?: boolean
    batch_generation?: boolean
    async_job?: boolean
  }
  settings: {
    temperature?: number | null
  }
  limits: {
    max_input_tokens?: number | null
    compression_trigger_tokens?: number | null
    max_output_tokens?: number | null
    timeout_seconds?: number | null
  }
  pricing: {
    currency: string
    input_per_1m_tokens?: number | null
    output_per_1m_tokens?: number | null
    cache_hit_per_1m_tokens?: number | null
    image_input_unit_price?: number | null
    image_output_unit_price?: number | null
    image_edit_unit_price?: number | null
  }
  notes: string
  credential?: ModelPoolCredential | null
}

export function isAvailableChatModelProfile(profile: ModelPoolProfile): boolean {
  return (
    profile.kind === 'chat'
    && profile.enabled
    && profile.credential?.enabled !== false
    && profile.credential?.has_api_key === true
  )
}

export async function resolveRuntimeMainModelProfileId(
  profiles: ModelPoolProfile[],
  preferredProfileId?: string | null,
): Promise<string> {
  const availableProfiles = profiles.filter(isAvailableChatModelProfile)
  if (availableProfiles.length === 0) return ''

  const availableIds = new Set(availableProfiles.map(profile => profile.profile_id))
  const preferredId = String(preferredProfileId || '').trim()
  if (availableIds.has(preferredId)) return preferredId

  try {
    const roleBindings = await modelPoolApi.roleBindings()
    const configuredId = String(roleBindings.bindings.main || '').trim()
    if (availableIds.has(configuredId)) return configuredId
  } catch {
    // The loaded profiles remain usable even if optional role bindings are unavailable.
  }

  try {
    const selection = await modelPoolApi.select({
      requirements: [{
        role: 'main',
        purpose: 'Runtime main conversation model',
        kind: 'chat',
        input_modalities: ['text'],
        output_modalities: ['text'],
        tool_calling: true,
        structured_output_methods: ['json_mode', 'function_calling'],
        optimize_for: 'balanced',
      }],
    })
    const recommendedId = String(
      selection.recommendations.find(item => item.role === 'main')?.profile_id || ''
    ).trim()
    if (availableIds.has(recommendedId)) return recommendedId
  } catch {
    // Fall back to the first available profile when recommendation is unavailable.
  }
  return availableProfiles[0].profile_id
}

export interface ModelUsageTotals {
  call_count: number
  input_tokens: number
  output_tokens: number
  total_tokens: number
  reasoning_tokens: number
  cache_hit_tokens: number
  cache_miss_tokens: number
  cache_hit_ratio: number | null
  estimated_cost: number | null
}

export interface ModelUsageGroup {
  key: string
  label: string
  provider: string
  provider_display_name: string
  model_name: string
  model_profile_id: string
  agent_id: string
  agent_label: string
  totals: ModelUsageTotals
}

export interface ModelUsageSeries {
  key: string
  label: string
  points: Array<{ bucket: string } & ModelUsageTotals>
}

export interface ModelSelectionRecommendation {
  role: 'main' | 'task' | 'compression' | 'embedding'
  profile_id: string
}

export interface ModelSelectionResult {
  status: 'completed' | 'blocked'
  recommendations: ModelSelectionRecommendation[]
  unmatched: Array<Record<string, unknown>>
}

export interface ModelUsageSummary {
  group_by: ModelUsageGroupBy
  since: string
  until: string
  totals: ModelUsageTotals
  groups: ModelUsageGroup[]
  series: ModelUsageSeries[]
}

export const modelPoolApi = {
  providers: () => requestJson<{ providers: ModelProviderProfile[] }>('/api/model-pool/providers'),
  credentials: () => requestJson<{ credentials: ModelPoolCredential[] }>('/api/model-pool/credentials'),
  saveCredential: (payload: Record<string, unknown>) =>
    requestJson<{ credential: ModelPoolCredential }>('/api/model-pool/credentials', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  patchCredential: (credentialId: string, payload: Record<string, unknown>) =>
    requestJson<{ credential: ModelPoolCredential }>(`/api/model-pool/credentials/${encodeURIComponent(credentialId)}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  deleteCredential: (credentialId: string) =>
    requestJson<{ deleted: boolean }>(`/api/model-pool/credentials/${encodeURIComponent(credentialId)}`, {
      method: 'DELETE',
    }),
  profiles: () => requestJson<{ profiles: ModelPoolProfile[] }>('/api/model-pool/profiles'),
  roleBindings: () =>
    requestJson<{ bindings: ModelRoleBindings; defaults: ModelPoolDefaults }>('/api/model-pool/role-bindings'),
  saveRoleBindings: (bindings: ModelRoleBindings) =>
    requestJson<{ bindings: ModelRoleBindings }>('/api/model-pool/role-bindings', {
      method: 'PUT',
      body: JSON.stringify({ bindings }),
    }),
  select: (payload: Record<string, unknown>) =>
    requestJson<ModelSelectionResult>('/api/model-pool/select', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  saveProfile: (payload: Record<string, unknown>) =>
    requestJson<{ profile: ModelPoolProfile }>('/api/model-pool/profiles', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  patchProfile: (profileId: string, payload: Record<string, unknown>) =>
    requestJson<{ profile: ModelPoolProfile }>(`/api/model-pool/profiles/${encodeURIComponent(profileId)}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  deleteProfile: (profileId: string) =>
    requestJson<{ deleted: boolean }>(`/api/model-pool/profiles/${encodeURIComponent(profileId)}`, {
      method: 'DELETE',
    }),
  pingProfile: (profileId: string) =>
    requestJson<{ status: 'ok'; profile_id: string; latency_ms: number; response_preview?: string; dimensions?: number }>(
      `/api/model-pool/profiles/${encodeURIComponent(profileId)}/ping`,
      { method: 'POST' },
    ),
  usage: (params: { groupBy?: ModelUsageGroupBy; days?: number } = {}) =>
    requestJson<ModelUsageSummary>(
      withQuery('/api/model-pool/usage', {
        group_by: params.groupBy,
        days: params.days,
      }),
    ),
}
