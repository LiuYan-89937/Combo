import { invoke, isTauri } from '@tauri-apps/api/core'

export function desktopDirectoryPickerAvailable(): boolean {
  return isTauri()
}

export async function selectDesktopDirectory(initialPath?: string): Promise<string | null> {
  if (!desktopDirectoryPickerAvailable()) {
    throw new Error('Directory selection is available only in the desktop application')
  }
  return invoke<string | null>('select_directory', {
    initialPath: initialPath?.trim() || null,
  })
}
