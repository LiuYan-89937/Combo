import { requestJson, withQuery } from './http'

export interface AgentHubUser {
  user_id: string
  github_login: string
  display_name: string
  avatar_url: string
  is_admin: boolean
}

export interface AgentHubAuthStatus {
  authenticated: boolean
  user: AgentHubUser | null
  hub_url: string
}

export interface AgentHubBrowserAuthorization {
  flow_id: string
  poll_secret: string
  authorization_url: string
  expires_in: number
  interval: number
}

export interface AgentHubValidation {
  dependencies?: {
    python_count?: number
    npm_count?: number
    system_count?: number
    python?: string[]
    npm?: string[]
    system?: string[]
  }
  tools?: {
    package_tools?: string[]
    mcp_servers?: string[]
    builtin_tools?: string[]
  }
  warnings?: Array<{ code: string; message: string; path?: string }>
}

export interface AgentHubRelease {
  release_id: string
  publisher: string
  package_id: string
  name: string
  description: string
  version: string
  sha256: string
  size_bytes: number
  status: string
  validation: AgentHubValidation | null
  download_count: number
  published_at: string
}

export interface AgentHubPackageList {
  items: AgentHubRelease[]
  total: number
  limit: number
  offset: number
}

export interface AgentHubUpload {
  upload_id: string
  filename: string
  expected_size: number
  actual_size: number | null
  status: string
  error: { code: string; message: string } | null
  validation: AgentHubValidation | null
  created_at: string
  updated_at: string
}

export interface AgentHubSkillFileDraft {
  path: string
  size_bytes: number
  kind: 'text' | 'binary'
  included: boolean
  content: string | null
}

export interface AgentHubSkillDraft {
  skill_id: string
  source: string
  enabled: boolean
  required: boolean
  path: string
  files: AgentHubSkillFileDraft[]
}

export interface AgentHubPublishPreview {
  package_id: string
  mcp_servers: Record<string, unknown>
  skills: AgentHubSkillDraft[]
}

export const agentHubApi = {
  auth: () => requestJson<AgentHubAuthStatus>('/api/agent-hub/auth'),
  startBrowserLogin: () =>
    requestJson<AgentHubBrowserAuthorization>('/api/agent-hub/auth/browser/start', { method: 'POST' }),
  pollBrowserLogin: (flowId: string, pollSecret: string) =>
    requestJson<{ status: string; retry_after_seconds?: number; user?: AgentHubUser }>(
      '/api/agent-hub/auth/browser/poll',
      {
        method: 'POST',
        body: JSON.stringify({ flow_id: flowId, poll_secret: pollSecret }),
      },
    ),
  cancelBrowserLogin: (flowId: string, pollSecret: string) =>
    requestJson<{ status: 'cancelled' }>('/api/agent-hub/auth/browser/cancel', {
      method: 'POST',
      body: JSON.stringify({ flow_id: flowId, poll_secret: pollSecret }),
    }),
  logout: () => requestJson<{ authenticated: false }>('/api/agent-hub/auth/logout', { method: 'POST' }),
  packages: (query = '', limit = 40, offset = 0) =>
    requestJson<AgentHubPackageList>(
      withQuery('/api/agent-hub/packages', { q: query, limit, offset }),
    ),
  uploads: (limit = 50) =>
    requestJson<AgentHubUpload[]>(withQuery('/api/agent-hub/uploads', { limit })),
  install: (releaseId: string, replace = false) =>
    requestJson<{ release: AgentHubRelease; package: Record<string, unknown> }>(
      `/api/agent-hub/releases/${encodeURIComponent(releaseId)}/install`,
      {
        method: 'POST',
        body: JSON.stringify({ replace }),
      },
    ),
  publishPreview: (packageId: string) =>
    requestJson<AgentHubPublishPreview>(
      `/api/agent-hub/packages/${encodeURIComponent(packageId)}/publish-preview`,
    ),
  publish: (
    packageId: string,
    extensions: {
      mcp_servers: Record<string, unknown>
      skills: Array<{
        skill_id: string
        files: Array<{ path: string; included: boolean; content: string | null }>
      }>
    },
  ) =>
    requestJson<AgentHubUpload>(
      `/api/agent-hub/packages/${encodeURIComponent(packageId)}/publish`,
      {
        method: 'POST',
        body: JSON.stringify({
          confirmed_sensitive_review: true,
          extensions,
        }),
      },
    ),
}
