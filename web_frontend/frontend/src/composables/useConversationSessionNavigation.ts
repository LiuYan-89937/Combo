import { computed } from 'vue'
import { useAgentSessionNavigation } from '@/composables/agent/useAgentSessionNavigation'
import { useCommand } from '@/composables/useCommand'
import { useAgentStore } from '@/stores/agent'
import { useRuntimeStore } from '@/stores/runtime'

type FactoryConversationMode = 'chat' | 'create_agent' | 'evolve_agent'

export function useConversationSessionNavigation() {
  const commands = useCommand()
  const agentStore = useAgentStore()
  const runtimeStore = useRuntimeStore()
  const { startNewAgentSession } = useAgentSessionNavigation()
  const canStartNewConversationSession = computed(() => (
    Boolean(agentStore.activeChatPackageId) || !runtimeStore.hasActiveRun
  ))

  function activeFactoryMode(): FactoryConversationMode {
    if (runtimeStore.currentMode === 'create_agent') return 'create_agent'
    if (runtimeStore.currentMode === 'evolve_agent') return 'evolve_agent'
    return 'chat'
  }

  async function startNewConversationSession(): Promise<void> {
    if (!canStartNewConversationSession.value) return
    const packageId = agentStore.activeChatPackageId
    if (packageId) {
      await startNewAgentSession(packageId)
      return
    }
    const mode = activeFactoryMode()
    const evolutionPackageId = mode === 'evolve_agent' ? agentStore.selectedPackageId : null
    runtimeStore.showEmptyFactoryConversation(mode, evolutionPackageId)
    commands.newSession(mode, evolutionPackageId)
  }

  return {
    activeFactoryMode,
    canStartNewConversationSession,
    startNewConversationSession,
  }
}
