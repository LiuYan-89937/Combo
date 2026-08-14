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

export interface GitHubDeviceAuthorization {
  device_code: string
  user_code: string
  verification_uri: string
  expires_in: number
  interval: number
}

interface GitHubDevicePoll {
  status: 'authorized' | 'authorization_pending' | 'slow_down' | 'expired_token' | 'access_denied'
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
  async login(onWaiting?: (flow: GitHubDeviceAuthorization) => void): Promise<GitHubAccount> {
    requireDesktop()
    const flow = await invoke<GitHubDeviceAuthorization>('github_start_device_authorization')
    await open(flow.verification_uri)
    onWaiting?.(flow)
    const deadline = Date.now() + flow.expires_in * 1000
    let interval = Math.max(5, flow.interval)
    while (Date.now() < deadline) {
      await delay(interval * 1000)
      const result = await invoke<GitHubDevicePoll>('github_poll_device_authorization', {
        deviceCode: flow.device_code,
      })
      if (result.status === 'authorized' && result.account) return result.account
      if (result.status === 'slow_down') interval = Math.max(interval + 5, result.retry_after_seconds)
      if (result.status === 'expired_token') throw new Error('GitHub authorization expired')
      if (result.status === 'access_denied') throw new Error('GitHub authorization was cancelled')
    }
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
