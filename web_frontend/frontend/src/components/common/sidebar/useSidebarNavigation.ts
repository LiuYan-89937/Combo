import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from '@/composables/useI18n'
import { sidebarMenuOptions } from './sidebarMenu'
import { useAgentSessionNavigation } from '@/composables/agent/useAgentSessionNavigation'
import { isAgentPackageRoute } from '@/utils/agentSessionRoute'
import { SYSTEM_CHAT_PACKAGE_ID } from '@/utils/resourceScope'

export function useSidebarNavigation() {
  const router = useRouter()
  const route = useRoute()
  const { t } = useI18n()
  const { openAgentSessions } = useAgentSessionNavigation()

  const activeKey = computed(() => (
    route.path === '/factory' && isAgentPackageRoute(route.query)
      ? 'agent-sessions'
      : route.path
  ))
  const menuOptions = computed(() => sidebarMenuOptions(t))

  function handleMenuSelect(key: string) {
    if (key === 'agent-sessions') {
      void openAgentSessions()
      return
    }
    if (key === '/factory') {
      void router.push({
        name: 'Factory',
        query: { package_id: SYSTEM_CHAT_PACKAGE_ID },
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
