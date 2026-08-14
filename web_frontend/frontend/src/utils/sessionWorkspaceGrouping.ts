export interface SessionWorkspaceSummary {
  workspace_id: string
  title: string
  mode: 'isolated' | 'project'
  root_kind: 'managed' | 'linked'
  workdir_root: string
}

export interface WorkspaceGroupedSession {
  session_id: string
  workspace_id?: string | null
  workspace?: SessionWorkspaceSummary | null
}

export interface WorkspaceSessionGroup<T extends WorkspaceGroupedSession> {
  kind: 'workspace'
  key: string
  workspaceId: string
  name: string
  path: string
  sessions: T[]
}

export interface StandaloneSessionGroup<T extends WorkspaceGroupedSession> {
  kind: 'session'
  key: string
  session: T
}

export type GroupedSessionEntry<T extends WorkspaceGroupedSession> =
  | WorkspaceSessionGroup<T>
  | StandaloneSessionGroup<T>

export function groupSessionsByWorkspace<T extends WorkspaceGroupedSession>(
  sessions: readonly T[],
): GroupedSessionEntry<T>[] {
  const entries: GroupedSessionEntry<T>[] = []
  const workspaceGroups = new Map<string, WorkspaceSessionGroup<T>>()

  for (const session of sessions) {
    const workspace = session.workspace
    const workspaceId = String(workspace?.workspace_id || session.workspace_id || '').trim()
    if (!workspace || workspace.mode !== 'project' || !workspaceId) {
      entries.push({ kind: 'session', key: `session:${session.session_id}`, session })
      continue
    }

    const existing = workspaceGroups.get(workspaceId)
    if (existing) {
      existing.sessions.push(session)
      continue
    }

    const group: WorkspaceSessionGroup<T> = {
      kind: 'workspace',
      key: `workspace:${workspaceId}`,
      workspaceId,
      name: workspaceFolderName(workspace),
      path: workspace.workdir_root,
      sessions: [session],
    }
    workspaceGroups.set(workspaceId, group)
    entries.push(group)
  }

  return entries
}

function workspaceFolderName(workspace: SessionWorkspaceSummary): string {
  const normalizedPath = workspace.workdir_root.trim().replace(/[\\/]+$/, '')
  const pathSegments = normalizedPath.split(/[\\/]/).filter(Boolean)
  return pathSegments.at(-1) || workspace.title
}
