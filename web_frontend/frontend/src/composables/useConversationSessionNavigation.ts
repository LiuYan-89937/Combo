import { computed } from 'vue'
import { useAgentSessionNavigation } from '@/composables/agent/useAgentSessionNavigation'
import { useAgentStore } from '@/stores/agent'

export function useConversationSessionNavigation() {
  const agentStore = useAgentStore()
  const { startNewAgentSession } = useAgentSessionNavigation()
  const canStartNewConversationSession = computed(() => Boolean(agentStore.activeChatPackageId))

  async function startNewConversationSession(): Promise<void> {
    if (!canStartNewConversationSession.value) return
    await startNewAgentSession(agentStore.activeChatPackageId as string)
  }

  return {
    canStartNewConversationSession,
    startNewConversationSession,
  }
}
