import { invoke, isTauri } from '@tauri-apps/api/core'

export type GitChangeType = 'added' | 'modified' | 'deleted' | 'renamed' | 'copied' | 'type_changed' | 'conflicted'

export interface GitFileStatus {
  path: string
  change_type: GitChangeType
  staged: boolean
  additions: number
  deletions: number
}

export interface GitRepositoryStatus {
  repository_root: string
  branch: string | null
  detached: boolean
  ahead: number
  behind: number
  files: GitFileStatus[]
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

export interface GitRevertResult {
  reverted: boolean
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
    return invoke<GitRevertResult>('git_revert_turn', { path, requestId })
  },
}
