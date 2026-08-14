import { invoke, isTauri } from '@tauri-apps/api/core'
import { listen, type UnlistenFn } from '@tauri-apps/api/event'
import { open } from '@tauri-apps/plugin-shell'

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

interface GitHubBrowserAuthorization {
  flow_id: string
  poll_secret: string
  authorization_url: string
  expires_in: number
  interval: number
}

interface GitHubBrowserPoll {
  status: 'authorized' | 'authorization_pending'
  retry_after_seconds: number
  account: GitHubAccount | null
}

function requireDesktop(): void {
  if (!isTauri()) throw new Error('GitHub workspaces are available in the Combo desktop app')
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
    const flow = await invoke<GitHubBrowserAuthorization>('github_start_browser_authorization')
    const deadline = Date.now() + flow.expires_in * 1000
    let authorized = false
    try {
      await open(flow.authorization_url)
      onWaiting?.()
      let retryAfterSeconds = Math.max(1, flow.interval)
      while (Date.now() < deadline) {
        const result = await invoke<GitHubBrowserPoll>('github_poll_browser_authorization', {
          flowId: flow.flow_id,
          pollSecret: flow.poll_secret,
        })
        if (result.status === 'authorized' && result.account) {
          authorized = true
          return result.account
        }
        retryAfterSeconds = Math.max(retryAfterSeconds, result.retry_after_seconds)
        await delay(retryAfterSeconds * 1000)
      }
      throw new Error('GitHub authorization expired')
    } finally {
      if (!authorized) {
        await invoke('github_cancel_browser_authorization', {
          flowId: flow.flow_id,
          pollSecret: flow.poll_secret,
        }).catch(() => undefined)
      }
    }
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
