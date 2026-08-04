/*
 * API contract types. Defined once, mirrored from the backend registry views.
 * Pages and stores must import from here rather than redeclaring shapes.
 */

/** Static validation report (agenthub.package_inspection.v1). */
export interface ValidationReport {
  inspection_version: string
  package_id: string
  name: string
  description: string
  version: string
  sha256: string
  archive_size: number
  file_count: number
  uncompressed_size: number
  package_root: string
  dependencies: {
    python: string[]
    npm: string[]
    system: string[]
    python_count: number
    npm_count: number
    system_count: number
  }
  tools: {
    builtin_tools: string[]
    package_tools: string[]
    mcp_servers: string[]
    permissions: Record<string, unknown> | unknown[]
  }
  model: {
    requirements: Record<string, unknown> | unknown[]
    profile_references: string[]
  }
  warnings: Array<{ code: string; path?: string; message: string }>
}

export interface AgentRelease {
  release_id: string
  publisher: string
  package_id: string
  name: string
  description: string
  version: string
  sha256: string
  size_bytes: number
  status: string
  validation: ValidationReport | null
  changelog: string
  download_count: number
  created_at: string
  published_at: string
  updated_at: string
  /** Present only on admin/detail views. */
  review_message?: string
}

export interface PackageListResponse {
  items: AgentRelease[]
  total: number
  limit: number
  offset: number
}

export interface AgentPackageDetail {
  publisher: string
  package_id: string
  name: string
  description: string
  latest: AgentRelease
  versions: AgentRelease[]
}

export interface HubUser {
  user_id: string
  github_login: string
  display_name: string
  avatar_url: string
  is_admin: boolean
}

export type UploadStatus =
  | 'awaiting_upload'
  | 'queued'
  | 'validating'
  | 'pending_review'
  | 'rejected'
  | 'published'
  | 'failed'

export interface HubUpload {
  upload_id: string
  filename: string
  expected_size: number
  actual_size: number | null
  status: UploadStatus
  error: { code: string; message: string } | null
  validation: ValidationReport | null
  created_at: string
  updated_at: string
}

/** Signed OSS PUT request returned by POST /uploads. */
export interface UploadRequest {
  method: string
  url: string
  headers: Record<string, string>
  expires_in_seconds: number
}

export interface CreateUploadResponse {
  upload: HubUpload
  upload_request: UploadRequest
}

export type AppReleaseStatus =
  | 'draft'
  | 'queued'
  | 'publishing'
  | 'published'
  | 'failed'
  | 'withdrawn'

export type AppAssetStatus =
  | 'awaiting_upload'
  | 'uploaded'
  | 'publishing'
  | 'published'
  | 'failed'

export interface AppReleaseAsset {
  asset_id: string
  asset_kind: 'installer' | 'updater'
  platform: 'macos' | 'windows'
  architecture: string
  filename: string
  content_type: string
  size_bytes: number
  sha256: string
  status: AppAssetStatus
  download_url: string
  download_count: number
  created_at: string
  updated_at: string
  expected_size?: number
  progress_bytes?: number
  progress_ratio?: number
  has_updater_signature?: boolean
  error?: { code: string; message: string } | null
}

export interface AppReleaseJob {
  job_id: string
  job_type: 'publish' | 'sync_metadata'
  status: 'queued' | 'running' | 'succeeded' | 'failed'
  stage: string
  progress_bytes: number
  total_bytes: number
  progress_ratio: number
  error: { code: string; message: string } | null
  created_at: string
  updated_at: string
}

export interface AppRelease {
  app_release_id: string
  version: string
  tag_name: string
  title: string
  notes_markdown: string
  status: AppReleaseStatus
  github_url: string
  created_at: string
  published_at: string
  updated_at: string
  assets: AppReleaseAsset[]
  error?: { code: string; message: string } | null
  latest_job?: AppReleaseJob | null
}

export interface CreateAppAssetResponse {
  asset: AppReleaseAsset
  upload_request: UploadRequest
}

/** Machine-readable API error envelope. */
export interface ApiErrorBody {
  code: string
  message: string
  request_id?: string
}
