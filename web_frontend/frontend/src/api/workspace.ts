import type { WorkspaceScope } from './resourceTypes'
import { requestEvent, withQuery } from './http'

export const workspaceApi = {
  roots: (packageId?: string) => requestEvent(withQuery('/api/workspace/roots', { package_id: packageId })),
  entries: (scope: WorkspaceScope, path: string, packageId?: string) =>
    requestEvent(withQuery('/api/workspace/entries', { scope, path, package_id: packageId })),
  file: (scope: WorkspaceScope, path: string, packageId?: string, maxChars?: number) =>
    requestEvent(withQuery('/api/workspace/file', { scope, path, package_id: packageId, max_chars: maxChars })),
  rawUrl: (scope: WorkspaceScope, path: string, packageId?: string | null) =>
    withQuery('/api/workspace/raw', { scope, path, package_id: packageId }),
}
