import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from '@/composables/useI18n'
import { useAgentStore } from '@/stores/agent'
import { sidebarMenuOptions } from './sidebarMenu'
import { useAgentSessionNavigation } from '@/composables/agent/useAgentSessionNavigation'

export function useSidebarNavigation() {
  const router = useRouter()
  const route = useRoute()
  const agentStore = useAgentStore()
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
    void router.push(key)
  }

  return {
    activeKey,
    handleMenuSelect,
    menuOptions,
  }
}
