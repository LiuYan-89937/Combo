import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { isTauri } from '@tauri-apps/api/core'
import { gitApi, type GitTurnChanges } from '@/api/git'

interface TrackedTurn {
  requestId: string
  workspacePath: string
  phase: 'started' | 'completed' | 'failed'
  changes: GitTurnChanges | null
  error: string | null
}

export const useGitChangesStore = defineStore('gitChanges', () => {
  const turns = ref<Record<string, TrackedTurn>>({})
  const pendingLoads = new Set<string>()

  const activeTurns = computed(() => Object.values(turns.value).filter(turn => turn.phase === 'started'))

  async function beginTurn(workspacePath: string, requestId: string): Promise<void> {
    if (!isTauri() || !workspacePath || !requestId) return
    try {
      await gitApi.snapshot(workspacePath, requestId, 'before')
      turns.value = {
        ...turns.value,
        [requestId]: {
          requestId,
          workspacePath,
          phase: 'started',
          changes: null,
          error: null,
        },
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      if (message.includes('not a Git repository')) return
      turns.value = {
        ...turns.value,
        [requestId]: {
          requestId,
          workspacePath,
          phase: 'failed',
          changes: null,
          error: message,
        },
      }
    }
  }

  async function completeTurn(requestId: string): Promise<void> {
    const tracked = turns.value[requestId]
    if (!tracked || tracked.phase !== 'started') return
    try {
      const changes = await gitApi.snapshot(tracked.workspacePath, requestId, 'after')
      turns.value = {
        ...turns.value,
        [requestId]: { ...tracked, phase: 'completed', changes, error: null },
      }
    } catch (error) {
      turns.value = {
        ...turns.value,
        [requestId]: {
          ...tracked,
          phase: 'failed',
          error: error instanceof Error ? error.message : String(error),
        },
      }
    }
  }

  async function captureCompletedTurn(workspacePath: string, requestId: string): Promise<void> {
    if (!isTauri() || !workspacePath || !requestId || pendingLoads.has(requestId)) return
    const existing = turns.value[requestId]
    if (existing?.phase === 'completed' || existing?.phase === 'failed') return
    pendingLoads.add(requestId)
    try {
      if (existing?.phase === 'started') {
        await completeTurn(requestId)
        return
      }
      let changes: GitTurnChanges
      try {
        changes = await gitApi.turnChanges(workspacePath, requestId)
      } catch {
        changes = await gitApi.snapshot(workspacePath, requestId, 'after')
      }
      turns.value = {
        ...turns.value,
        [requestId]: {
          requestId,
          workspacePath,
          phase: 'completed',
          changes,
          error: null,
        },
      }
    } catch {
      // Sessions created before Git tracking have no private snapshot refs.
    } finally {
      pendingLoads.delete(requestId)
    }
  }

  function changesFor(requestId: string | null | undefined): GitTurnChanges | null {
    const key = String(requestId || '').trim()
    return key ? turns.value[key]?.changes || null : null
  }

  function workspacePathFor(requestId: string): string | null {
    return turns.value[requestId]?.workspacePath || null
  }

  return { turns, activeTurns, beginTurn, completeTurn, captureCompletedTurn, changesFor, workspacePathFor }
})
