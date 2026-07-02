import { computed } from 'vue'
import { useAgentStore } from '@/stores/agent'
import { useRuntimeStore } from '@/stores/runtime'
import { useI18n } from '@/composables/useI18n'

export function useResourceContext() {
  const agentStore = useAgentStore()
  const runtimeStore = useRuntimeStore()
  const { t } = useI18n()

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
    if (!packageId.value) return t('resource.chat')
    const pkg = packageInfo.value
    const prefix = runtimeStore.currentMode === 'evolve_agent' ? t('resource.evolution') : t('resource.subAgent')
    return `${prefix} · ${pkg?.agent_name || pkg?.name || t('common.unnamedAgent')}`
  })

  return {
    packageId,
    packageIdForApi,
    packageInfo,
    isAgentContext,
    label,
  }
}
