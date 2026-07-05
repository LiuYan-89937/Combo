import { computed } from 'vue'
import { useAgentStore } from '@/stores/agent'
import { useRuntimeStore } from '@/stores/runtime'
import { useI18n } from '@/composables/useI18n'
import { SYSTEM_CHAT_PACKAGE_ID } from '@/utils/resourceScope'
import type { WorkspaceRequestContext, WorkspaceScope } from '@/api/resourceTypes'

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

  const activeFactorySession = computed(() => (
    runtimeStore.sessions.find((session: any) => session.session_id === runtimeStore.activeFactorySessionId) || null
  ))
  const createAgentSessionId = computed(() => (
    String(activeFactorySession.value?.create_agent_session_id || '').trim() || null
  ))
  const chatAgentPackageSessionId = computed(() => (
    String(activeFactorySession.value?.chat_agent_package_session_id || runtimeStore.activeAgentSessionId || '').trim() || null
  ))
  const workspaceContext = computed<WorkspaceRequestContext>(() => {
    if (runtimeStore.currentMode === 'create_agent') {
      return {
        resourceMode: 'create_agent',
        factorySessionId: runtimeStore.activeFactorySessionId,
        createAgentSessionId: createAgentSessionId.value,
      }
    }
    if (runtimeStore.currentMode === 'evolve_agent') {
      return {
        resourceMode: 'evolve_agent',
        packageId: agentStore.selectedPackageId,
        factorySessionId: runtimeStore.activeFactorySessionId,
      }
    }
    if (agentStore.activeChatPackageId) {
      return {
        resourceMode: 'package',
        packageId: agentStore.activeChatPackageId,
        packageSessionId: agentStore.selectedSessionId || runtimeStore.activeAgentSessionId,
      }
    }
    return {
      resourceMode: 'package',
      packageId: SYSTEM_CHAT_PACKAGE_ID,
      packageSessionId: chatAgentPackageSessionId.value,
      factorySessionId: runtimeStore.activeFactorySessionId,
    }
  })
  const workspaceContextKey = computed(() => [
    workspaceContext.value.resourceMode || '',
    workspaceContext.value.packageId || '',
    workspaceContext.value.packageSessionId || '',
    workspaceContext.value.factorySessionId || '',
    workspaceContext.value.createAgentSessionId || '',
    workspaceContext.value.collaborationId || '',
  ].join(':'))
  const workspaceDefaultScope = computed<WorkspaceScope>(() => (
    workspaceContext.value.resourceMode === 'create_agent' || workspaceContext.value.resourceMode === 'evolve_agent'
      ? 'package'
      : 'workdir'
  ))
  const packageIdForApi = computed(() => packageId.value || SYSTEM_CHAT_PACKAGE_ID)
  const isAgentContext = computed(() => Boolean(packageId.value))
  const label = computed(() => {
    if (runtimeStore.currentMode === 'create_agent') return t('resource.manufacturing')
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
    workspaceContext,
    workspaceContextKey,
    workspaceDefaultScope,
  }
}
