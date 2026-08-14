import { requestFormJson, requestFormProgress, requestJson, requestJsonProgress, type OperationProgress, withQuery } from './http'
import type { McpServerConfig } from './resourceTypes'

export type CapabilityKind = 'skill' | 'tool' | 'mcp_server' | 'mcp_tool'

export interface CapabilityPoolItem {
  capability_id: string
  kind: CapabilityKind
  namespace: string
  display_name: string
  description: string
  keywords: string[]
  revision: number
  resolved_version: string
  content_digest: string
  source_uri: string
  trust_level: string
  health: string | null
  indexing: {
    vector: boolean
    generation_id: string | null
    embedding_profile_id: string | null
  }
  definition_schema: string
  details: Record<string, unknown>
}

export interface CapabilityPoolSnapshot {
  counts: Record<CapabilityKind, number>
  capabilities: CapabilityPoolItem[]
  mcp_registry_digest: string
}

export interface MainAgentCapabilityProfile {
  version: 'main_agent_capability_profile.v1'
  revision: number
  capability_ids: string[]
}

export interface McpProbeResult {
  capability_id: string
  content_digest: string
  tool_count: number
  tools: string[]
  protocol_version: string
  server_name: string
  server_version: string
  capabilities: string[]
  resource_count: number
  resources: string[]
  resource_template_count: number
  prompt_count: number
  prompts: string[]
}

export interface McpResourceReadResult {
  server_id: string
  uri: string
  result: Record<string, unknown>
}

export interface McpPromptGetResult {
  server_id: string
  name: string
  result: Record<string, unknown>
}

export interface ToolRuntimePolicyInput {
  approval: 'inherit' | 'allow' | 'ask' | 'deny'
  risk_level: 'low' | 'medium' | 'high'
  allow_parallel_calls: boolean
  max_parallel_calls: number
  timeout_seconds: number
  output_projection: 'compress' | 'passthrough'
  output_max_model_chars: number
  retain_raw_output: boolean
}

export interface ToolPackageCreateInput {
  name: string
  model_alias: string
  display_name: string
  description: string
  keywords: string[]
  parameters: Array<{
    name: string
    type: 'string' | 'integer' | 'number' | 'boolean' | 'object' | 'array'
    description: string
    required: boolean
  }>
  dependencies: string[]
  runtime_policy: ToolRuntimePolicyInput
}

export interface SkillEditorResource {
  path: string
  size_bytes: number
  editable: boolean
  content: string | null
}

export interface SkillEditorDocument {
  capability_id: string
  content_digest: string
  source_path: string
  metadata: Record<string, unknown>
  instructions: string
  resources: SkillEditorResource[]
}

export interface SkillHubResult {
  action: 'status' | 'search' | 'install'
  status: string
  message: string
  cli_available: boolean
  cli_version: string
  items: Array<{
    name: string
    install_name: string
    version: string
    summary: string
    source: string
  }>
}

export interface SkillHubInstallResult {
  skillhub: SkillHubResult
  capability_pool: CapabilityPoolSnapshot
}

export interface ToolPackageEditorDocument {
  capability_id: string
  content_digest: string
  source_path: string
  entrypoint: string
  python_requirements: string[]
  files: SkillEditorResource[]
}

export const capabilityPoolsApi = {
  snapshot: () => requestJson<CapabilityPoolSnapshot>('/api/runtime/capabilities'),
  mainAgentProfile: () => requestJson<MainAgentCapabilityProfile>('/api/runtime/main-agent-capability-profile'),
  updateMainAgentProfile: (profile: Pick<MainAgentCapabilityProfile, 'revision' | 'capability_ids'>) =>
    requestJson<MainAgentCapabilityProfile>('/api/runtime/main-agent-capability-profile', {
      method: 'PUT',
      body: JSON.stringify({
        expected_revision: profile.revision,
        capability_ids: profile.capability_ids,
      }),
    }),
  skillHubStatus: () => requestJson<SkillHubResult>('/api/runtime/capabilities/skillhub/status'),
  searchSkillHub: (query: string) => requestJson<SkillHubResult>('/api/runtime/capabilities/skillhub/search', {
    method: 'POST',
    body: JSON.stringify({ query }),
  }),
  installSkillHub: (skill: string) => requestJson<SkillHubInstallResult>('/api/runtime/capabilities/skillhub/install', {
    method: 'POST',
    body: JSON.stringify({ skill }),
  }),
  importSkillFolder: (rootName: string, files: Array<{ file: File; relativePath: string }>) => {
    const formData = new FormData()
    formData.append('root_name', rootName)
    formData.append('relative_paths', JSON.stringify(files.map(item => item.relativePath)))
    files.forEach(item => formData.append('files', item.file, item.file.name))
    return requestFormJson<CapabilityPoolSnapshot>('/api/runtime/capabilities/skills/import', formData)
  },
  importToolFolder: (
    rootName: string,
    files: Array<{ file: File; relativePath: string }>,
    onProgress: (progress: OperationProgress) => void,
  ) => {
    const formData = new FormData()
    formData.append('root_name', rootName)
    formData.append('relative_paths', JSON.stringify(files.map(item => item.relativePath)))
    files.forEach(item => formData.append('files', item.file, item.file.name))
    return requestFormProgress<CapabilityPoolSnapshot>(
      '/api/runtime/capabilities/tools/import',
      formData,
      onProgress,
    )
  },
  createToolPackage: (
    input: ToolPackageCreateInput,
    mainSource: string,
    onProgress: (progress: OperationProgress) => void,
  ) => {
    const formData = new FormData()
    formData.append('specification', JSON.stringify(input))
    formData.append('main_file', new File([mainSource], 'main.py', { type: 'text/x-python' }))
    return requestFormProgress<CapabilityPoolSnapshot>(
      '/api/runtime/capabilities/tools',
      formData,
      onProgress,
    )
  },
  probeMcp: (capabilityId: string) => requestJson<McpProbeResult>('/api/runtime/capabilities/mcp/probe', {
    method: 'POST',
    body: JSON.stringify({ capability_id: capabilityId }),
  }),
  readMcpResource: (
    capabilityId: string,
    reference: { uri: string } | { uri_template: string; arguments: Record<string, string> },
  ) => requestJson<McpResourceReadResult>(
    '/api/runtime/capabilities/mcp/resource',
    { method: 'POST', body: JSON.stringify({ capability_id: capabilityId, ...reference }) },
  ),
  getMcpPrompt: (capabilityId: string, name: string, arguments_: Record<string, string>) =>
    requestJson<McpPromptGetResult>('/api/runtime/capabilities/mcp/prompt', {
      method: 'POST',
      body: JSON.stringify({ capability_id: capabilityId, name, arguments: arguments_ }),
    }),
  addMcp: (
    server: McpServerConfig,
    expectedRegistryDigest: string,
    onProgress: (progress: OperationProgress) => void,
    signal?: AbortSignal,
  ) =>
    requestJsonProgress<CapabilityPoolSnapshot>('/api/runtime/capabilities/mcp', {
      method: 'POST',
      body: JSON.stringify(mcpWritePayload(server, expectedRegistryDigest)),
      signal,
    }, onProgress),
  updateMcp: (
    serverId: string,
    server: McpServerConfig,
    expectedRegistryDigest: string,
    onProgress: (progress: OperationProgress) => void,
    signal?: AbortSignal,
  ) =>
    requestJsonProgress<CapabilityPoolSnapshot>(`/api/runtime/capabilities/mcp/${encodeURIComponent(serverId)}`, {
      method: 'PUT',
      body: JSON.stringify(mcpWritePayload({ ...server, server_id: serverId }, expectedRegistryDigest)),
      signal,
    }, onProgress),
  deleteMcp: (serverId: string, expectedRegistryDigest: string) =>
    requestJson<CapabilityPoolSnapshot>(withQuery(
      `/api/runtime/capabilities/mcp/${encodeURIComponent(serverId)}`,
      { expected_registry_digest: expectedRegistryDigest },
    ), { method: 'DELETE' }),
  deleteSkill: (item: Pick<CapabilityPoolItem, 'capability_id' | 'content_digest'>) =>
    requestJson<CapabilityPoolSnapshot>(withQuery(
      `/api/runtime/capabilities/skills/${encodeURIComponent(item.capability_id)}`,
      { expected_content_digest: item.content_digest },
    ), { method: 'DELETE' }),
  deleteTool: (item: Pick<CapabilityPoolItem, 'capability_id' | 'content_digest'>) =>
    requestJson<CapabilityPoolSnapshot>(withQuery(
      `/api/runtime/capabilities/tools/${encodeURIComponent(item.capability_id)}`,
      { expected_content_digest: item.content_digest },
    ), { method: 'DELETE' }),
  updateSkill: (capabilityId: string, sourcePath: string, expectedContentDigest: string) =>
    requestJson<CapabilityPoolSnapshot>('/api/runtime/capabilities/skills', {
      method: 'PUT',
      body: JSON.stringify({
        capability_id: capabilityId,
        source_path: sourcePath,
        expected_content_digest: expectedContentDigest,
      }),
    }),
  updateTool: (
    item: Pick<CapabilityPoolItem, 'capability_id' | 'content_digest'>,
    input: { display_name: string; description: string; runtime_policy: ToolRuntimePolicyInput },
  ) => requestJson<CapabilityPoolSnapshot>(
    `/api/runtime/capabilities/tools/${encodeURIComponent(item.capability_id)}`,
    {
      method: 'PUT',
      body: JSON.stringify({ expected_content_digest: item.content_digest, ...input }),
    },
  ),
  toolPackageEditor: (capabilityId: string) => requestJson<ToolPackageEditorDocument>(
    `/api/runtime/capabilities/tool-packages/${encodeURIComponent(capabilityId)}/editor`,
  ),
  updateToolPackageContent: (
    document: ToolPackageEditorDocument,
    files: Record<string, string>,
  ) => requestJson<CapabilityPoolSnapshot>(
    `/api/runtime/capabilities/tool-packages/${encodeURIComponent(document.capability_id)}/editor`,
    {
      method: 'PUT',
      body: JSON.stringify({ expected_content_digest: document.content_digest, files }),
    },
  ),
  skillEditor: (capabilityId: string) => requestJson<SkillEditorDocument>(
    `/api/runtime/capabilities/skills/${encodeURIComponent(capabilityId)}/editor`,
  ),
  updateSkillContent: (
    document: SkillEditorDocument,
    input: { metadata: Record<string, unknown>; instructions: string; resources: Record<string, string> },
  ) => requestJson<CapabilityPoolSnapshot>(
    `/api/runtime/capabilities/skills/${encodeURIComponent(document.capability_id)}/editor`,
    {
      method: 'PUT',
      body: JSON.stringify({ expected_content_digest: document.content_digest, ...input }),
    },
  ),
}

function mcpWritePayload(server: McpServerConfig, expectedRegistryDigest: string) {
  return {
    expected_registry_digest: expectedRegistryDigest,
    server_id: server.server_id || generatedServerId(),
    display_name: server.display_name,
    description: server.description || server.display_name,
    transport: server.transport,
    command: server.transport === 'stdio' ? server.command : null,
    arguments: server.transport === 'stdio' ? argumentList(server.args) : [],
    working_directory: server.transport === 'stdio' ? server.cwd || null : null,
    endpoint: server.transport === 'stdio' ? null : server.url,
    environment_bindings: bindingRecord(server.env),
    header_bindings: bindingRecord(server.headers),
    request_timeout_seconds: server.timeout_seconds,
    connect_timeout_seconds: server.connect_timeout_seconds ?? 30,
    max_parallel_requests: server.max_parallel_requests ?? 1,
    risk_level_default: server.risk_level_default || 'medium',
    concurrent_default: server.concurrent_default ?? true,
  }
}

function generatedServerId(): string {
  const randomPart = globalThis.crypto?.randomUUID?.().replace(/-/g, '').slice(0, 12)
    || Math.random().toString(36).slice(2, 14)
  return `mcp_${randomPart}`
}

function argumentList(value: McpServerConfig['args']): string[] {
  if (Array.isArray(value)) return value.map(String).filter(Boolean)
  return String(value || '').trim().split(/\s+/).filter(Boolean)
}

function bindingRecord(value: string | Record<string, unknown> | undefined): Record<string, unknown> {
  if (!value) return {}
  if (typeof value === 'object') return value
  return Object.fromEntries(
    value.split(/\r?\n/).map(line => line.trim()).filter(Boolean).map((line) => {
      const separator = line.indexOf('=')
      return separator < 0
        ? [line, line]
        : [line.slice(0, separator).trim(), line.slice(separator + 1).trim()]
    }).filter(([key, source]) => Boolean(key && source)),
  )
}
