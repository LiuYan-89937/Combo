import { isTauri } from '@tauri-apps/api/core'
import { runtimeAttachmentNativePath } from '@/api/attachments'
import {
  openNativePathWithSystemApp,
  openWorkspaceEntryWithSystemApp,
} from '@/api/desktopWorkspaceFiles'
import type { WorkspaceContextInput, WorkspaceScope } from '@/api/resourceTypes'

export interface SystemViewerTarget {
  /** Workspace-relative path, present when the attachment already lives in the workspace. */
  path?: string | null
  scope?: WorkspaceScope | null
  /** Staged upload id, the only handle when the file is still in the upload store. */
  attachmentId?: string | null
  /** Blob URL used as the fallback outside the desktop app. */
  fallbackUrl?: string | null
}

/** Whether a file can be handed to a system application at all. */
export function systemViewerAvailable(): boolean {
  return isTauri()
}

/**
 * Opens an attachment with the operating system's default application.
 *
 * Two storage shapes have to be handled: workspace files resolve to a native
 * path through the workspace API, while staged uploads only expose their local
 * path through the attachment API. Outside the desktop app there is no system
 * viewer to call, so the caller-provided blob URL is used instead.
 */
export async function openAttachmentWithSystemViewer(
  target: SystemViewerTarget,
  context?: WorkspaceContextInput,
): Promise<void> {
  const path = String(target.path || '').trim()
  const attachmentId = String(target.attachmentId || '').trim()

  if (!isTauri()) {
    if (target.fallbackUrl) {
      window.open(target.fallbackUrl, '_blank', 'noopener,noreferrer')
      return
    }
    throw new Error('System viewer is unavailable')
  }

  if (path && context) {
    await openWorkspaceEntryWithSystemApp(target.scope || 'workdir', path, context)
    return
  }
  if (attachmentId) {
    const resolved = await runtimeAttachmentNativePath(attachmentId)
    await openNativePathWithSystemApp(resolved.native_path)
    return
  }
  if (path) {
    // Workspace-relative path without a workspace context cannot be resolved.
    throw new Error('Attachment location is unavailable')
  }
  throw new Error('Attachment location is unavailable')
}
