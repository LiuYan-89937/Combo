import { computed } from 'vue'
import { useAgentStore } from '@/stores/agent'
import { useRuntimeStore } from '@/stores/runtime'

export function useResourceContext() {
  const agentStore = useAgentStore()
  const runtimeStore = useRuntimeStore()

  const packageId = computed(() => {
    if (agentStore.activeChatPackageId) return agentStore.activeChatPackageId
    if (runtimeStore.currentMode === 'evolve_agent' && agentStore.selectedPackageId) {
      return agentStore.selectedPackageId
    }
    return null
  })

  const packageInfo = computed(() => {
    if (!packageId.value) return null
    return agentStore.agentPackages.find((pkg) => pkg.package_id === packageId.value) || null
  })

  const packageIdForApi = computed(() => packageId.value || undefined)
  const isAgentContext = computed(() => Boolean(packageId.value))
  const label = computed(() => {
    if (!packageId.value) return '闲聊'
    const pkg = packageInfo.value
    return `子 Agent · ${pkg?.agent_name || pkg?.name || '未命名 Agent'}`
  })

  return {
    packageId,
    packageIdForApi,
    packageInfo,
    isAgentContext,
    label,
  }
}
