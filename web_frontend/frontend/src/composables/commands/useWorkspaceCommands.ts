import { workspaceApi } from '@/api/workspace'
import type { WorkspaceScope } from '@/api/resourceTypes'
import { useCommandTransport } from './transport'

export function useWorkspaceCommands() {
  const transport = useCommandTransport()

  const refreshWorkspace = (scope: WorkspaceScope, path: string, packageId?: string) => {
    return transport.applyEventRequest(workspaceApi.entries(scope, path, packageId))
  }

  const readFile = (scope: WorkspaceScope, path: string, packageId?: string, maxChars?: number) => {
    return transport.applyEventRequest(workspaceApi.file(scope, path, packageId, maxChars))
  }

  return {
    refreshWorkspace,
    readFile,
  }
}
