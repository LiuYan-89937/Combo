import { invoke, isTauri } from '@tauri-apps/api/core'
import { workspaceApi } from './workspace'
import type { WorkspaceContextInput, WorkspaceScope } from './resourceTypes'

export function desktopWorkspaceFileActionsAvailable(): boolean {
  return isTauri()
}

export async function revealWorkspaceEntry(
  scope: WorkspaceScope,
  path: string,
  context?: WorkspaceContextInput,
): Promise<void> {
  requireDesktopRuntime()
  const resolved = await workspaceApi.nativePath(scope, path, context)
  await invoke('reveal_in_file_manager', { sourcePath: resolved.native_path })
}

export async function revealNativePath(path: string): Promise<void> {
  requireDesktopRuntime()
  await invoke('reveal_in_file_manager', { sourcePath: path })
}

/**
 * Saves a copy of an absolute native file chosen by the user.
 *
 * Separate from `saveWorkspaceFileAs`, which resolves its path through the
 * workspace API and therefore cannot handle files addressed by absolute path.
 */
export async function saveNativeFileAs(path: string): Promise<string | null> {
  requireDesktopRuntime()
  return invoke<string | null>('save_file_as', { sourcePath: path })
}

/**
 * Hands a file to the operating system's default application.
 *
 * Used for attachments: the in-app lightbox covers quick inspection, but the
 * system image viewer is what people reach for when they want real zooming or to
 * step through the folder.
 */
export async function openNativePathWithSystemApp(path: string): Promise<void> {
  requireDesktopRuntime()
  await invoke('open_with_system_app', { sourcePath: path })
}

export async function openWorkspaceEntryWithSystemApp(
  scope: WorkspaceScope,
  path: string,
  context?: WorkspaceContextInput,
): Promise<void> {
  requireDesktopRuntime()
  const resolved = await workspaceApi.nativePath(scope, path, context)
  await invoke('open_with_system_app', { sourcePath: resolved.native_path })
}

export async function saveWorkspaceFileAs(
  scope: WorkspaceScope,
  path: string,
  context?: WorkspaceContextInput,
): Promise<string | null> {
  requireDesktopRuntime()
  const resolved = await workspaceApi.nativePath(scope, path, context)
  if (resolved.kind !== 'file') {
    throw new Error('Only workspace files can be saved as a copy')
  }
  return invoke<string | null>('save_file_as', { sourcePath: resolved.native_path })
}

function requireDesktopRuntime(): void {
  if (!desktopWorkspaceFileActionsAvailable()) {
    throw new Error('This action is available only in the desktop application')
  }
}
