import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from '@/composables/useI18n'
import { useCommand } from '@/composables/useCommand'
import { useAgentStore } from '@/stores/agent'
import { useRuntimeStore } from '@/stores/runtime'
import { sidebarMenuOptions } from './sidebarMenu'
import { useAgentSessionNavigation } from '@/composables/agent/useAgentSessionNavigation'

export function useSidebarNavigation() {
  const router = useRouter()
  const route = useRoute()
  const agentStore = useAgentStore()
  const runtimeStore = useRuntimeStore()
  const commands = useCommand()
  const { t } = useI18n()
  const { openMostRecentAgentSession } = useAgentSessionNavigation()

  const activeKey = computed(() => (
    route.path === '/factory' && agentStore.activeChatPackageId ? 'agent-sessions' : route.path
  ))
  const menuOptions = computed(() => sidebarMenuOptions(t))

  function handleMenuSelect(key: string) {
    if (key === 'agent-sessions') {
      void openMostRecentAgentSession().then((opened) => {
        if (!opened) void router.push({ name: 'Agents' })
      })
      return
    }
    if (!key.startsWith('/')) return
    if (key === '/factory') {
      enterFactoryMode('chat')
    } else if (key === '/manufacturing') {
      enterFactoryMode('create_agent')
    } else if (key === '/evolution') {
      agentStore.leaveAgentChat()
      const packageId = agentStore.selectedPackageId
      runtimeStore.enterFactoryConversation('evolve_agent', packageId)
      if (packageId) {
        commands.selectAgentPackage(packageId, 'evolution')
      } else {
        commands.startSession(true, 'evolve_agent')
      }
    }
    router.push(key)
  }

  function enterFactoryMode(mode: 'chat' | 'create_agent') {
    const needsSessionRestore = runtimeStore.currentMode !== mode
      || Boolean(agentStore.activeChatPackageId)
      || runtimeStore.isCollaborationConversationActive
    agentStore.leaveAgentChat()
    runtimeStore.enterFactoryConversation(mode)
    if (needsSessionRestore) {
      commands.startSession(true, mode)
    }
  }

  return {
    activeKey,
    handleMenuSelect,
    menuOptions,
  }
}
