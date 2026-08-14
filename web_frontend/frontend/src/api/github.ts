import { invoke, isTauri } from '@tauri-apps/api/core'
import { listen, type UnlistenFn } from '@tauri-apps/api/event'
import { open } from '@tauri-apps/plugin-shell'

const COMBO_SERVICE_URL = String(import.meta.env.VITE_COMBO_SERVICE_URL || 'https://liuyanai.top').replace(/\/$/, '')

export interface GitHubAccount {
  login: string
  display_name: string
  avatar_url: string
}

export interface GitHubRepository {
  id: number
  name: string
  full_name: string
  private: boolean
  clone_url: string
  default_branch: string
  owner_login: string
  owner_avatar_url: string
  updated_at: string
}

export interface GitCloneProgress {
  stage: 'connecting' | 'receiving' | 'complete'
  received_objects: number
  total_objects: number
  indexed_objects: number
  received_bytes: number
}

interface DesktopLoginStart {
  flow_id: string
  poll_secret: string
  authorization_url: string
  expires_in: number
  interval: number
}

interface DesktopLoginResult {
  status: 'authorized'
  access_token: string
  github_access_token: string
  user: {
    github_login: string
    display_name: string
    avatar_url: string
  }
}

function requireDesktop(): void {
  if (!isTauri()) throw new Error('GitHub workspaces are available in the Combo desktop app')
}

async function serviceRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${COMBO_SERVICE_URL}${path}`, {
    ...init,
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...(init?.headers || {}) },
  })
  if (response.status === 202) {
    const pending = await response.json().catch(() => ({}))
    throw new AuthorizationPending(Number(pending.retry_after_seconds || response.headers.get('Retry-After') || 3))
  }
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(String(payload?.error?.message || payload?.message || `HTTP ${response.status}`))
  }
  return payload as T
}

class AuthorizationPending extends Error {
  constructor(readonly retryAfterSeconds: number) {
    super('authorization_pending')
  }
}

export const githubApi = {
  account() {
    requireDesktop()
    return invoke<GitHubAccount | null>('github_account')
  },
  repositories() {
    requireDesktop()
    return invoke<GitHubRepository[]>('github_list_repositories')
  },
  logout() {
    requireDesktop()
    return invoke<void>('github_logout')
  },
  async login(onWaiting?: () => void): Promise<GitHubAccount> {
    requireDesktop()
    const flow = await serviceRequest<DesktopLoginStart>('/api/v1/auth/github/desktop/start', { method: 'POST' })
    await open(flow.authorization_url)
    onWaiting?.()
    const deadline = Date.now() + flow.expires_in * 1000
    while (Date.now() < deadline) {
      try {
        const result = await serviceRequest<DesktopLoginResult>('/api/v1/auth/github/desktop/poll', {
          method: 'POST',
          body: JSON.stringify({ flow_id: flow.flow_id, poll_secret: flow.poll_secret }),
        })
        const account: GitHubAccount = {
          login: result.user.github_login,
          display_name: result.user.display_name || result.user.github_login,
          avatar_url: result.user.avatar_url,
        }
        return invoke<GitHubAccount>('github_store_account', {
          account,
          comboSessionToken: result.access_token,
          githubAccessToken: result.github_access_token,
        })
      } catch (error) {
        if (!(error instanceof AuthorizationPending)) throw error
        await delay(Math.max(flow.interval, error.retryAfterSeconds) * 1000)
      }
    }
    await serviceRequest('/api/v1/auth/github/desktop/cancel', {
      method: 'POST',
      body: JSON.stringify({ flow_id: flow.flow_id, poll_secret: flow.poll_secret }),
    }).catch(() => undefined)
    throw new Error('GitHub authorization expired')
  },
  clone(
    repository: GitHubRepository,
    destinationParent: string,
    onProgress: (progress: GitCloneProgress) => void,
  ) {
    requireDesktop()
    return cloneWithProgress(repository, destinationParent, onProgress)
  },
}

async function cloneWithProgress(
  repository: GitHubRepository,
  destinationParent: string,
  onProgress: (progress: GitCloneProgress) => void,
): Promise<{ repository_root: string; branch: string | null }> {
  let unlisten: UnlistenFn | null = await listen<GitCloneProgress>('git-clone-progress', event => onProgress(event.payload))
  try {
    return await invoke('git_clone_repository', {
      remoteUrl: repository.clone_url,
      destinationParent,
      directoryName: repository.name,
      branch: repository.default_branch,
    })
  } finally {
    unlisten?.()
    unlisten = null
  }
}

function delay(milliseconds: number): Promise<void> {
  return new Promise(resolve => window.setTimeout(resolve, milliseconds))
}
