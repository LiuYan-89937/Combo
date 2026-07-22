import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from '@/composables/useI18n'
import { useAgentStore } from '@/stores/agent'
import { sidebarMenuOptions } from './sidebarMenu'
import { useAgentSessionNavigation } from '@/composables/agent/useAgentSessionNavigation'
import { isAgentSessionsLanding } from '@/utils/agentSessionRoute'

export function useSidebarNavigation() {
  const router = useRouter()
  const route = useRoute()
  const agentStore = useAgentStore()
  const { t } = useI18n()
  const { openAgentSessions } = useAgentSessionNavigation()

  const activeKey = computed(() => (
    route.path === '/factory' && (agentStore.activeChatPackageId || isAgentSessionsLanding(route.query))
      ? 'agent-sessions'
      : route.path
  ))
  const menuOptions = computed(() => sidebarMenuOptions(t))

  function handleMenuSelect(key: string) {
    if (key === 'agent-sessions') {
      void openAgentSessions()
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
