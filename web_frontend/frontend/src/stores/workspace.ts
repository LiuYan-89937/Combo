/**
 * Workspace Store
 * 管理工作区文件浏览和预览
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { WorkspaceScope, WorkspaceEntry, WorkspaceFileView, WorkspaceRootView } from '@/types/protocol'

export const useWorkspaceStore = defineStore('workspace', () => {
  const currentScope = ref<WorkspaceScope>('workdir')
  const currentPath = ref('')
  const roots = ref<WorkspaceRootView[]>([])
  const entries = ref<WorkspaceEntry[]>([])
  const currentFile = ref<WorkspaceFileView | null>(null)
  const expandedDirs = ref<Set<string>>(new Set())

  const pathParts = computed(() => {
    if (!currentPath.value) return []
    return currentPath.value.split('/').filter(Boolean)
  })

  const parentPath = computed(() => {
    const parts = pathParts.value
    if (parts.length === 0) return ''
    return parts.slice(0, -1).join('/')
  })

  function setScope(scope: WorkspaceScope): void {
    currentScope.value = scope
    currentPath.value = ''
    entries.value = []
  }

  function setPath(path: string): void {
    currentPath.value = path
  }

  function navigateUp(): void {
    currentPath.value = parentPath.value
  }

  function navigateTo(path: string): void {
    currentPath.value = path
  }

  function setRoots(newRoots: WorkspaceRootView[]): void {
    roots.value = newRoots
  }

  function setEntries(newEntries: WorkspaceEntry[]): void {
    entries.value = newEntries
  }

  function setCurrentFile(file: WorkspaceFileView | null): void {
    currentFile.value = file
  }

  function toggleDir(path: string): void {
    if (expandedDirs.value.has(path)) {
      expandedDirs.value.delete(path)
    } else {
      expandedDirs.value.add(path)
    }
  }

  function clearExpandedDirs(): void {
    expandedDirs.value.clear()
  }

  return {
    currentScope,
    currentPath,
    roots,
    entries,
    currentFile,
    expandedDirs,
    pathParts,
    parentPath,
    setScope,
    setPath,
    navigateUp,
    navigateTo,
    setRoots,
    setEntries,
    setCurrentFile,
    toggleDir,
    clearExpandedDirs,
  }
})
