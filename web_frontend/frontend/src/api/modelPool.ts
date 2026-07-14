import { requestJson, withQuery } from './http'

export type LocalModelKind = 'chat' | 'embedding'
export type LocalInferenceEngine = 'llama_cpp_rocm' | 'transformers_rocm'
export type LocalModelDefaultRole = 'main' | 'task' | 'compression' | 'embedding'
export type ModelUsageGroupBy = 'model' | 'provider' | 'agent'

export type LocalModelDefaults = Record<LocalModelDefaultRole, string | null>

export interface LocalEngine {
  engine: LocalInferenceEngine
  display_name: string
  kind: LocalModelKind
  transport: string
  parameters: Record<string, unknown>
}

export interface LocalModelArtifact {
  artifact_id: string
  display_name: string
  kind: LocalModelKind
  local_path: string
  model_format: string
  revision: string
  checksum: string
  license: string
  enabled: boolean
  created_at: string
  updated_at: string
}

export interface LocalModelDirectory {
  relative_path: string
  absolute_path: string
  display_name: string
  model_type: string
  dtype: string
  embedding_dimensions?: number | null
  architectures: string[]
  tokenizer_available: boolean
  supported_kinds: LocalModelKind[]
}

export interface LocalModelStorage {
  root_path: string
  modelscope_cache_path: string
  directories: LocalModelDirectory[]
}

interface LocalModelProfileBase {
  profile_id: string
  display_name: string
  artifact_id: string
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
    context_compression_threshold_tokens?: number | null
  }
  embedding_dimensions?: number | null
  normalize_embeddings: boolean
  notes: string
  artifact?: LocalModelArtifact | null
}

export interface LocalChatModelProfile extends LocalModelProfileBase {
  kind: 'chat'
  engine: 'llama_cpp_rocm'
  inference: {
    gpu_layers: number
    parallel_slots: number
    cache_type_k: string
    cache_type_v: string
    flash_attention: boolean
  }
}

export interface LocalEmbeddingModelProfile extends LocalModelProfileBase {
  kind: 'embedding'
  engine: 'transformers_rocm'
  inference: {
    trust_remote_code: boolean
  }
}

export type LocalModelProfile = LocalChatModelProfile | LocalEmbeddingModelProfile

export type LocalModelRuntimePhase = 'idle' | 'starting' | 'loading' | 'ready' | 'stopping' | 'failed'

export interface LocalModelRuntime {
  kind: LocalModelKind
  profile_id: string
  phase: LocalModelRuntimePhase
  stage: string
  progress_percent?: number | null
  pid?: number | null
  error: string
  started_at: string
  updated_at: string
  logs: string[]
}

export interface LocalModelRuntimeSummary {
  runtimes: LocalModelRuntime[]
  rocm: RocmRuntimeInfo
}

export interface RocmRuntimeInfo {
  available: boolean
  torch_version: string
  hip_version: string
  rocm_version: string
  device_count: number
  devices: RocmDeviceInfo[]
  telemetry_source: string
  error: string
}

export interface RocmDeviceInfo {
  index: number
  name: string
  total_memory_bytes: number
  used_memory_bytes?: number | null
  gpu_utilization_percent?: number | null
  memory_activity_percent?: number | null
  temperature_edge_celsius?: number | null
  temperature_hotspot_celsius?: number | null
  temperature_memory_celsius?: number | null
  power_watts?: number | null
  architecture: string
  pci_bus: string
  pci_device_id: string
  vram_type: string
  compute_units?: number | null
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
  runtimes: () => requestJson<LocalModelRuntimeSummary>('/api/model-pool/runtimes'),
  rocmRuntime: () => requestJson<RocmRuntimeInfo>('/api/model-pool/runtime/rocm'),
  storage: () => requestJson<LocalModelStorage>('/api/model-pool/storage'),
  defaults: () => requestJson<{ defaults: LocalModelDefaults }>('/api/model-pool/defaults'),
  setDefault: (role: LocalModelDefaultRole, profileId: string) =>
    requestJson<{ role: LocalModelDefaultRole; profile_id: string | null }>(
      `/api/model-pool/defaults/${encodeURIComponent(role)}`,
      {
        method: 'PUT',
        body: JSON.stringify({ profile_id: profileId }),
      },
    ),
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
    requestJson<{ profile: LocalModelProfile; runtime: LocalModelRuntime }>('/api/model-pool/profiles', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  patchProfile: (profileId: string, payload: Record<string, unknown>) =>
    requestJson<{ profile: LocalModelProfile; runtime: LocalModelRuntime }>(`/api/model-pool/profiles/${encodeURIComponent(profileId)}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  deleteProfile: (profileId: string) =>
    requestJson<{ deleted: boolean }>(`/api/model-pool/profiles/${encodeURIComponent(profileId)}`, {
      method: 'DELETE',
    }),
  loadProfile: (profileId: string) =>
    requestJson<{ runtime: LocalModelRuntime }>(`/api/model-pool/profiles/${encodeURIComponent(profileId)}/load`, {
      method: 'POST',
    }),
  unloadProfile: (profileId: string) =>
    requestJson<{ runtime: LocalModelRuntime }>(`/api/model-pool/profiles/${encodeURIComponent(profileId)}/unload`, {
      method: 'POST',
    }),
  restartProfile: (profileId: string) =>
    requestJson<{ runtime: LocalModelRuntime }>(`/api/model-pool/profiles/${encodeURIComponent(profileId)}/restart`, {
      method: 'POST',
    }),
  usage: (params: { groupBy?: ModelUsageGroupBy; days?: number } = {}) =>
    requestJson<ModelUsageSummary>(
      withQuery('/api/model-pool/usage', { group_by: params.groupBy, days: params.days }),
    ),
}
