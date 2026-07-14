import { requestJson, withQuery } from './http'

export type LocalModelKind = 'chat' | 'embedding'
export type LocalInferenceEngine = 'vllm_rocm' | 'transformers_rocm'
export type ModelUsageGroupBy = 'model' | 'provider' | 'agent'

export interface LocalEngine {
  engine: LocalInferenceEngine
  display_name: string
  kind: LocalModelKind
  transport: string
}

export interface LocalModelArtifact {
  artifact_id: string
  display_name: string
  kind: LocalModelKind
  local_path: string
  tokenizer_path?: string | null
  model_format: string
  revision: string
  checksum: string
  license: string
  enabled: boolean
  created_at: string
  updated_at: string
}

export interface LocalModelProfile {
  profile_id: string
  display_name: string
  kind: LocalModelKind
  artifact_id: string
  engine: LocalInferenceEngine
  served_model_name: string
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
  inference: {
    dtype: string
    quantization?: string | null
    tensor_parallel_size: number
    gpu_memory_utilization?: number | null
    trust_remote_code: boolean
  }
  embedding_dimensions?: number | null
  normalize_embeddings: boolean
  notes: string
  artifact?: LocalModelArtifact | null
}

export interface RocmRuntimeInfo {
  available: boolean
  torch_version: string
  hip_version: string
  device_count: number
  devices: Array<{ index: number; name: string; total_memory_bytes: number }>
  error: string
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

export interface ModelUsageSummary {
  group_by: ModelUsageGroupBy
  since: string
  until: string
  totals: ModelUsageTotals
  groups: Array<Record<string, unknown>>
  series: Array<Record<string, unknown>>
}

export const modelPoolApi = {
  engines: () => requestJson<{ engines: LocalEngine[] }>('/api/model-pool/engines'),
  rocmRuntime: () => requestJson<RocmRuntimeInfo>('/api/model-pool/runtime/rocm'),
  artifacts: () => requestJson<{ artifacts: LocalModelArtifact[] }>('/api/model-pool/artifacts'),
  saveArtifact: (payload: Record<string, unknown>) =>
    requestJson<{ artifact: LocalModelArtifact }>('/api/model-pool/artifacts', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  patchArtifact: (artifactId: string, payload: Record<string, unknown>) =>
    requestJson<{ artifact: LocalModelArtifact }>(`/api/model-pool/artifacts/${encodeURIComponent(artifactId)}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  deleteArtifact: (artifactId: string) =>
    requestJson<{ deleted: boolean }>(`/api/model-pool/artifacts/${encodeURIComponent(artifactId)}`, {
      method: 'DELETE',
    }),
  profiles: () => requestJson<{ profiles: LocalModelProfile[] }>('/api/model-pool/profiles'),
  saveProfile: (payload: Record<string, unknown>) =>
    requestJson<{ profile: LocalModelProfile }>('/api/model-pool/profiles', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  patchProfile: (profileId: string, payload: Record<string, unknown>) =>
    requestJson<{ profile: LocalModelProfile }>(`/api/model-pool/profiles/${encodeURIComponent(profileId)}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  deleteProfile: (profileId: string) =>
    requestJson<{ deleted: boolean }>(`/api/model-pool/profiles/${encodeURIComponent(profileId)}`, {
      method: 'DELETE',
    }),
  checkProfile: (profileId: string) =>
    requestJson<Record<string, unknown>>(`/api/model-pool/profiles/${encodeURIComponent(profileId)}/check`, {
      method: 'POST',
    }),
  usage: (params: { groupBy?: ModelUsageGroupBy; days?: number } = {}) =>
    requestJson<ModelUsageSummary>(
      withQuery('/api/model-pool/usage', { group_by: params.groupBy, days: params.days }),
    ),
}
