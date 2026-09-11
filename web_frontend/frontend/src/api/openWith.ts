import { invoke, isTauri } from '@tauri-apps/api/core'

/** A local application that can open a given file. */
export interface OpenWithApplication {
  name: string
  /** Absolute path of the application bundle/executable. */
  path: string
  is_default: boolean
}

function requireDesktop(): void {
  if (!isTauri()) {
    throw new Error('Open-with actions are available in the Combo desktop app')
  }
}

export const openWithApi = {
  /**
   * Applications registered on this machine for the file's type.
   *
   * Enumerated on demand: a single turn can touch dozens of files, so the list is
   * only fetched when a menu is actually opened.
   */
  list(sourcePath: string) {
    requireDesktop()
    return invoke<OpenWithApplication[]>('list_open_with_applications', { sourcePath })
  },
  open(sourcePath: string, applicationPath: string) {
    requireDesktop()
    return invoke<void>('open_with_application', { sourcePath, applicationPath })
  },
}

/** Whether the current runtime can enumerate/open files with system apps. */
export function openWithAvailable(): boolean {
  return isTauri()
}
