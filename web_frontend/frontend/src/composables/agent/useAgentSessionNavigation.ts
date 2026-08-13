import { useRouter } from 'vue-router'
import { useCommand } from '@/composables/useCommand'
import { useAgentStore, type AgentRecentSessionView } from '@/stores/agent'
import { SYSTEM_CHAT_PACKAGE_ID } from '@/utils/resourceScope'

export function useAgentSessionNavigation() {
  const router = useRouter()
  const commands = useCommand()
  const agentStore = useAgentStore()

  async function openAgentSession(session: AgentRecentSessionView): Promise<void> {
    const sessionId = String(session.session_id || '').trim()
    if (!sessionId) return
    await router.push({
      name: 'ChatSession',
      params: { sessionId },
    })
  }

  async function startNewAgentSession(packageId: string, workspaceId?: string | null): Promise<void> {
    if (String(packageId || '').trim() !== SYSTEM_CHAT_PACKAGE_ID) return
    const normalizedWorkspaceId = String(workspaceId || '').trim() || null
    await router.push({
      name: 'ChatNew',
      query: normalizedWorkspaceId ? { workspace: normalizedWorkspaceId } : {},
    })
  }

  async function openPackageAgentChat(packageId: string): Promise<void> {
    if (String(packageId || '').trim() !== SYSTEM_CHAT_PACKAGE_ID) return
    await openAgentSessions()
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
    await router.push({ name: 'ChatNew' })
  }

  return {
    openAgentSessions,
    openAgentSession,
    openMostRecentAgentSession,
    openPackageAgentChat,
    startNewAgentSession,
  }
}
