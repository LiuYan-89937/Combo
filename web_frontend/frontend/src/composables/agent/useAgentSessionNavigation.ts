import { useRouter } from 'vue-router'
import { useCommand } from '@/composables/useCommand'
import { useAgentStore, type AgentRecentSessionView } from '@/stores/agent'
import { useRuntimeStore } from '@/stores/runtime'
import { useUiStore } from '@/stores/ui'
import { useWorkspaceStore } from '@/stores/workspace'

export function useAgentSessionNavigation() {
  const router = useRouter()
  const commands = useCommand()
  const agentStore = useAgentStore()
  const runtimeStore = useRuntimeStore()
  const uiStore = useUiStore()
  const workspaceStore = useWorkspaceStore()

  function prepareAgentConversation(packageId: string, sessionId: string | null): void {
    agentStore.enterAgentChat(packageId, sessionId)
    if (sessionId) {
      runtimeStore.expectAgentPackageSession(packageId, sessionId)
    } else {
      runtimeStore.showEmptyAgentPackageSession(packageId)
    }
    workspaceStore.setScope('workdir')
    uiStore.openRightSidebar('workspace')
  }

  async function openAgentSession(session: AgentRecentSessionView): Promise<void> {
    await activateAgentSession(session, true)
  }

  async function activateAgentSession(session: AgentRecentSessionView, selectPackage: boolean): Promise<void> {
    prepareAgentConversation(session.package_id, session.session_id)
    await router.push({
      name: 'Factory',
      query: { package_id: session.package_id, session_id: session.session_id },
    })
    if (selectPackage) await commands.selectAgentPackage(session.package_id, 'run')
    await commands.loadAgentPackageSession(session.package_id, session.session_id)
  }

  async function startNewAgentSession(packageId: string): Promise<void> {
    await activateNewAgentSession(packageId, true)
  }

  async function activateNewAgentSession(packageId: string, selectPackage: boolean): Promise<void> {
    const normalizedPackageId = String(packageId || '').trim()
    if (!normalizedPackageId) return
    prepareAgentConversation(normalizedPackageId, null)
    await router.push({ name: 'Factory', query: { package_id: normalizedPackageId, new: '1' } })
    if (selectPackage) await commands.selectAgentPackage(normalizedPackageId, 'run')
  }

  async function openPackageAgentChat(packageId: string): Promise<void> {
    await commands.selectAgentPackage(packageId, 'run')
    await commands.listAgentPackageSessions(packageId)
    const preferred = preferredSessionForPackage(packageId)
    if (preferred) {
      await activateAgentSession(preferred, false)
      return
    }
    await activateNewAgentSession(packageId, false)
  }

  async function openMostRecentAgentSession(): Promise<boolean> {
    await commands.listRecentAgentSessions(20)
    const preferred = agentStore.preferredRecentSession()
    if (!preferred) return false
    await openAgentSession(preferred)
    return true
  }

  function preferredSessionForPackage(packageId: string): AgentRecentSessionView | null {
    const persisted = agentStore.lastAgentSession
    const sessions = agentStore.agentSessions
      .filter((session) => session.package_id === packageId)
      .sort((left, right) => (right.updated_at || right.created_at).localeCompare(left.updated_at || left.created_at))
    const preferred = persisted?.packageId === packageId && persisted.sessionId
      ? sessions.find((session) => session.session_id === persisted.sessionId)
      : null
    const session = preferred || sessions[0]
    return session ? { ...session } : null
  }

  return {
    openAgentSession,
    openMostRecentAgentSession,
    openPackageAgentChat,
    startNewAgentSession,
  }
}
