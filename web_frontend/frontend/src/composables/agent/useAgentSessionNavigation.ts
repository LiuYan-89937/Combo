import { useRouter } from 'vue-router'
import { useCommand } from '@/composables/useCommand'
import { useAgentStore, type AgentRecentSessionView } from '@/stores/agent'
import { agentSessionsLandingQuery } from '@/utils/agentSessionRoute'

export function useAgentSessionNavigation() {
  const router = useRouter()
  const commands = useCommand()
  const agentStore = useAgentStore()

  async function openAgentSession(session: AgentRecentSessionView): Promise<void> {
    await router.push({
      name: 'Factory',
      query: { package_id: session.package_id, session_id: session.session_id },
    })
  }

  async function startNewAgentSession(packageId: string): Promise<void> {
    const normalizedPackageId = String(packageId || '').trim()
    if (!normalizedPackageId) return
    await router.push({ name: 'Factory', query: { package_id: normalizedPackageId, new: '1' } })
  }

  async function openPackageAgentChat(packageId: string): Promise<void> {
    const normalizedPackageId = String(packageId || '').trim()
    if (!normalizedPackageId) return
    await router.push({ name: 'Factory', query: { package_id: normalizedPackageId } })
  }

  async function openMostRecentAgentSession(): Promise<boolean> {
    await commands.listRecentAgentSessions(20)
    const preferred = agentStore.preferredRecentSession()
    if (!preferred) return false
    await openAgentSession(preferred)
    return true
  }

  async function openAgentSessions(): Promise<void> {
    const opened = await openMostRecentAgentSession()
    if (opened) return
    await router.push({ name: 'Factory', query: agentSessionsLandingQuery() })
  }

  return {
    openAgentSessions,
    openAgentSession,
    openMostRecentAgentSession,
    openPackageAgentChat,
    startNewAgentSession,
  }
}
