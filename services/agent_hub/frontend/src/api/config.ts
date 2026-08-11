import { request } from './client'

/**
 * Public runtime configuration.
 *
 * The backend exposes `GET /api/v1/config/public`. The centralized fallback
 * preserves the existing public downloads until the first database-managed
 * application release is published.
 */

export interface DownloadTarget {
  platform: 'macos' | 'windows'
  label: string
  arch: string
  /** Populated from a real release source; empty string disables the button. */
  url: string
  version: string
  sizeLabel: string
  downloadCount: number
}

export interface PublicConfig {
  githubRepoUrl: string
  downloads: DownloadTarget[]
  totalDownloadCount: number
  releaseManaged?: boolean
}

const FALLBACK_CONFIG: PublicConfig = {
  githubRepoUrl: 'https://github.com/LiuYan-89937/FastAgentFactory',
  downloads: [
    {
      platform: 'macos',
      label: 'macOS',
      arch: 'Apple Silicon',
      url: 'https://github.com/LiuYan-89937/FastAgentFactory/releases/download/v0.1.0/FastAgentFactory_0.1.0_aarch64.dmg',
      version: '0.1.0',
      sizeLabel: '296 MB',
      downloadCount: 0,
    },
    {
      platform: 'windows',
      label: 'Windows',
      arch: 'x64',
      url: 'https://github.com/LiuYan-89937/FastAgentFactory/releases/download/v0.1.0/FastAgentFactory_0.1.0_x64-setup.exe',
      version: '0.1.0',
      sizeLabel: '96.2 MB',
      downloadCount: 0,
    },
  ],
  totalDownloadCount: 0,
}

let cached: PublicConfig | null = null

/** Load public config once, preferring the server endpoint when available. */
export async function loadPublicConfig(): Promise<PublicConfig> {
  if (cached) return cached
  try {
    const remote = await request<Partial<PublicConfig>>('/config/public', { timeoutMs: 6_000 })
    cached = mergeConfig(remote)
  } catch {
    // Endpoint not implemented yet, or unreachable: use centralized defaults.
    cached = FALLBACK_CONFIG
  }
  return cached
}

function mergeConfig(remote: Partial<PublicConfig>): PublicConfig {
  return {
    githubRepoUrl: remote.githubRepoUrl || FALLBACK_CONFIG.githubRepoUrl,
    downloads: remote.releaseManaged
      ? remote.downloads ?? []
      : FALLBACK_CONFIG.downloads,
    totalDownloadCount: remote.totalDownloadCount ?? 0,
    releaseManaged: remote.releaseManaged ?? false,
  }
}

export { FALLBACK_CONFIG }
