import { requestJson } from './http'

export interface ModelProviderProfile {
  provider_id: string
  display_name: string
  adapter_id: string
  transport: string
  content_parts: Record<string, string>
  tools: Record<string, string>
  structured_output_methods: string[]
  default_structured_output_method: string
  reasoning: Record<string, unknown>
  cache_usage: string
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
  kind: 'chat'
  provider: string
  credential_id: string
  model_name: string
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
  }
  limits: {
    max_input_tokens?: number | null
    max_output_tokens?: number | null
    timeout_seconds?: number | null
  }
  pricing: {
    currency: string
    input_per_1m_tokens?: number | null
    output_per_1m_tokens?: number | null
    cache_hit_per_1m_tokens?: number | null
  }
  notes: string
  credential?: ModelPoolCredential | null
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
  profiles: () => requestJson<{ profiles: ModelPoolProfile[] }>('/api/model-pool/profiles?kind=chat'),
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
}
