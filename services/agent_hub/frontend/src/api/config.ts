import { request } from './client'

/**
 * Public runtime configuration.
 *
 * The backend does not yet expose `GET /api/v1/config/public` (tracked as a
 * required contract in FRONTEND_DEVELOPMENT.md §9). Until it does, every
 * value that would come from that endpoint lives here in ONE place so nothing
 * is hardcoded inside components. When the endpoint ships, `loadPublicConfig`
 * will prefer its response and fall back to these defaults.
 */

export interface DownloadTarget {
  platform: 'macos' | 'windows'
  label: string
  arch: string
  /** Populated from a real release source; empty string disables the button. */
  url: string
  version: string
  sizeLabel: string
}

export interface PublicConfig {
  /** Maximum upload size in bytes (backend default: 200 MiB). */
  maxPackageBytes: number
  githubRepoUrl: string
  downloads: DownloadTarget[]
}

const FALLBACK_CONFIG: PublicConfig = {
  maxPackageBytes: 200 * 1024 * 1024,
  githubRepoUrl: 'https://github.com/LiuYan-89937/FastAgentFactory',
  downloads: [
    {
      platform: 'macos',
      label: 'macOS',
      arch: 'Apple Silicon',
      url: 'https://github.com/LiuYan-89937/FastAgentFactory/releases/download/v0.1.0/FastAgentFactory_0.1.0_aarch64.dmg',
      version: '0.1.0',
      sizeLabel: '296 MB',
    },
    {
      platform: 'windows',
      label: 'Windows',
      arch: 'x64',
      url: 'https://github.com/LiuYan-89937/FastAgentFactory/releases/download/v0.1.0/FastAgentFactory_0.1.0_x64-setup.exe',
      version: '0.1.0',
      sizeLabel: '96.2 MB',
    },
  ],
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
    maxPackageBytes: remote.maxPackageBytes ?? FALLBACK_CONFIG.maxPackageBytes,
    githubRepoUrl: remote.githubRepoUrl ?? FALLBACK_CONFIG.githubRepoUrl,
    downloads:
      remote.downloads && remote.downloads.length > 0
        ? remote.downloads
        : FALLBACK_CONFIG.downloads,
  }
}

export { FALLBACK_CONFIG }
