import { invoke, isTauri } from '@tauri-apps/api/core'

export type GitChangeType = 'added' | 'modified' | 'deleted' | 'renamed' | 'copied' | 'type_changed' | 'conflicted'

export interface GitFileStatus {
  path: string
  change_type: GitChangeType
  staged: boolean
  unstaged: boolean
  additions: number
  deletions: number
}

export interface GitRepositoryStatus {
  repository_root: string
  branch: string | null
  detached: boolean
  has_head: boolean
  ahead: number
  behind: number
  remote_name: string | null
  remote_url: string | null
  has_upstream: boolean
  files: GitFileStatus[]
}

export interface GitRepositoryIdentity {
  name: string | null
  email: string | null
  configured: boolean
}

export type GitRemoteOutcome = 'fetched' | 'pulled' | 'pushed' | 'up_to_date' | 'conflicts'

export interface GitRemoteOperationResult {
  outcome: GitRemoteOutcome
  conflicting_files: string[]
  status: GitRepositoryStatus
}

export interface GitFileChange {
  old_path: string | null
  path: string
  change_type: GitChangeType
  additions: number
  deletions: number
  binary: boolean
}

export interface GitTurnChanges {
  request_id: string
  repository_root: string
  files: GitFileChange[]
  additions: number
  deletions: number
}

export interface GitFileDiff {
  old_path: string | null
  path: string
  old_content: string
  new_content: string
  binary: boolean
  truncated: boolean
}

export interface GitTurnApplyResult {
  applied: boolean
  affected_files: string[]
  conflicting_files: string[]
}

function requireDesktop(): void {
  if (!isTauri()) throw new Error('Git workspace features are available in the Combo desktop app')
}

export const gitApi = {
  repositoryStatus(path: string) {
    requireDesktop()
    return invoke<GitRepositoryStatus>('git_repository_status', { path })
  },
  initializeRepository(path: string) {
    requireDesktop()
    return invoke<GitRepositoryStatus>('git_initialize_repository', { path })
  },
  addRemote(path: string, remoteUrl: string) {
    requireDesktop()
    return invoke<GitRepositoryStatus>('git_add_remote', { path, remoteUrl })
  },
  repositoryIdentity(path: string) {
    requireDesktop()
    return invoke<GitRepositoryIdentity>('git_repository_identity', { path })
  },
  setRepositoryIdentity(path: string, name: string, email: string) {
    requireDesktop()
    return invoke<GitRepositoryIdentity>('git_set_repository_identity', { path, name, email })
  },
  stagePaths(path: string, filePaths: string[]) {
    requireDesktop()
    return invoke<GitRepositoryStatus>('git_stage_paths', { path, filePaths })
  },
  stageAll(path: string) {
    requireDesktop()
    return invoke<GitRepositoryStatus>('git_stage_all', { path })
  },
  unstagePaths(path: string, filePaths: string[]) {
    requireDesktop()
    return invoke<GitRepositoryStatus>('git_unstage_paths', { path, filePaths })
  },
  commit(path: string, message: string) {
    requireDesktop()
    return invoke<GitRepositoryStatus>('git_commit', { path, message })
  },
  fetch(path: string) {
    requireDesktop()
    return invoke<GitRemoteOperationResult>('git_fetch_repository', { path })
  },
  pull(path: string) {
    requireDesktop()
    return invoke<GitRemoteOperationResult>('git_pull_repository', { path })
  },
  push(path: string) {
    requireDesktop()
    return invoke<GitRemoteOperationResult>('git_push_repository', { path })
  },
  sync(path: string) {
    requireDesktop()
    return invoke<GitRemoteOperationResult>('git_sync_repository', { path })
  },
  snapshot(path: string, requestId: string, phase: 'before' | 'after') {
    requireDesktop()
    return invoke<GitTurnChanges>('git_begin_turn_snapshot', { path, requestId, phase })
  },
  turnChanges(path: string, requestId: string) {
    requireDesktop()
    return invoke<GitTurnChanges>('git_turn_changes', { path, requestId })
  },
  fileDiff(path: string, requestId: string, filePath: string) {
    requireDesktop()
    return invoke<GitFileDiff>('git_repository_diff', { path, requestId, filePath })
  },
  revertTurn(path: string, requestId: string) {
    requireDesktop()
    return invoke<GitTurnApplyResult>('git_revert_turn', { path, requestId })
  },
  reapplyTurn(path: string, requestId: string) {
    requireDesktop()
    return invoke<GitTurnApplyResult>('git_reapply_turn', { path, requestId })
  },
}
