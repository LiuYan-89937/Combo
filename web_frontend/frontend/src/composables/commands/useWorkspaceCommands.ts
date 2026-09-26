import { workspaceApi } from '@/api/workspace'
import type { WorkspaceContextInput, WorkspaceScope } from '@/api/resourceTypes'
import { useCommandTransport } from './transport'

export function useWorkspaceCommands() {
  const transport = useCommandTransport()

  const refreshWorkspace = (scope: WorkspaceScope, path: string, context?: WorkspaceContextInput) => {
    return transport.applyEventRequest(workspaceApi.entries(scope, path, context))
  }

  const readFile = (scope: WorkspaceScope, path: string, context?: WorkspaceContextInput, maxChars?: number) => {
    return transport.applyEventRequest(workspaceApi.file(scope, path, context, maxChars))
  }

  const deleteWorkspaceProject = (workspaceId: string) => {
    return transport.applyEventRequest(workspaceApi.deleteProject(workspaceId))
  }

  return {
    refreshWorkspace,
    readFile,
    deleteWorkspaceProject,
  }
}
