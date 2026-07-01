import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useAgentStore } from '@/stores/agent'
import { useRuntimeStore } from '@/stores/runtime'
import { useUiStore } from '@/stores/ui'
import { useWorkspaceStore } from '@/stores/workspace'
import { useCommand } from '@/composables/useCommand'
import type { FactoryMode } from '@/types/protocol'

export function useFactoryConversation() {
  const route = useRoute()
  const runtimeStore = useRuntimeStore()
  const agentStore = useAgentStore()
  const uiStore = useUiStore()
  const workspaceStore = useWorkspaceStore()
  const commands = useCommand()

  const isAgentChatActive = computed(() => Boolean(agentStore.activeChatPackageId))
  const isManufacturingRoute = computed(() => route.name === 'Manufacturing')
  const isEvolutionRoute = computed(() => route.name === 'Evolution')
  const currentFactoryMessageMode = computed<FactoryMode>(() => {
    if (isManufacturingRoute.value) return 'create_agent'
    if (isEvolutionRoute.value) return 'evolve_agent'
    return 'chat'
  })
  const activeChatPackageTitle = computed(() => {
    const pkg = agentStore.activeChatPackage
    return pkg?.agent_name || pkg?.name || '未命名 Agent'
  })
  const selectedEvolutionPackageId = computed(() => (
    isEvolutionRoute.value ? agentStore.selectedPackageId : null
  ))
  const selectedEvolutionPackageTitle = computed(() => {
    const pkg = agentStore.selectedPackage
    return pkg?.agent_name || pkg?.name || '当前 Agent'
  })
  const evolutionPackageOptions = computed(() => agentStore.agentPackages.map((pkg) => ({
    label: pkg.agent_name || pkg.name || pkg.package_id,
    value: pkg.package_id,
  })))
  const inputPlaceholder = computed(() => (
    isAgentChatActive.value
      ? `向 ${activeChatPackageTitle.value} 发送消息...`
      : currentFactoryMessageMode.value === 'create_agent'
        ? '描述要制造的 Agent...'
        : currentFactoryMessageMode.value === 'evolve_agent'
          ? selectedEvolutionPackageId.value
            ? `描述对 ${selectedEvolutionPackageTitle.value} 的进化方向...`
            : '先选择要进化的 Agent 包'
          : '输入消息...'
  ))
  const inputDisabled = computed(() => (
    runtimeStore.isInputLocked || (isEvolutionRoute.value && !selectedEvolutionPackageId.value)
  ))
  const emptyDescription = computed(() => {
    if (isEvolutionRoute.value) return selectedEvolutionPackageId.value ? '开始进化对话' : '选择进化对象'
    if (isManufacturingRoute.value) return '开始制造对话'
    return '开始对话'
  })
  const emptyHint = computed(() => {
    if (isEvolutionRoute.value) {
      return selectedEvolutionPackageId.value
        ? '在下方描述这次要进化的方向'
        : '先从上方选择一个已发布 Agent 包'
    }
    return '在下方输入框输入消息开始对话'
  })

  function handleEvolutionPackageSelect(packageId: string | null) {
    if (!packageId) return
    agentStore.leaveAgentChat()
    agentStore.selectPackage(packageId)
    runtimeStore.enterFactoryConversation('evolve_agent', packageId)
    workspaceStore.setScope('package')
    uiStore.openRightSidebar('workspace')
    void commands.selectAgentPackage(packageId, 'evolution')
  }

  function sendMessage(message: string, attachments: any[]): boolean {
    const packageId = agentStore.activeChatPackageId
    if (packageId) {
      const agentSessionId = agentStore.selectedSessionId || undefined
      const command = commands.sendAgentPackageMessage(packageId, message, agentSessionId)
      runtimeStore.addUserMessage(message, command.request_id, {
        mode: 'agent_package',
        package_id: packageId,
        agent_session_id: agentSessionId || null,
      })
      return true
    }

    const mode = currentFactoryMessageMode.value
    if (mode === 'evolve_agent' && !runtimeStore.isAwaitingUserInputInterrupt) {
      const evolutionPackageId = selectedEvolutionPackageId.value
      if (!evolutionPackageId) {
        uiStore.addNotification({
          type: 'warning',
          title: '请选择进化对象',
          message: '进化前需要先选择一个已发布 Agent 包。',
          duration: 3000,
        })
        return false
      }
      const command = commands.runAgentEvolution(evolutionPackageId, message)
      runtimeStore.addUserMessage(message, command.request_id, {
        mode,
        package_id: evolutionPackageId,
      })
      return true
    }

    const command = runtimeStore.isAwaitingUserInputInterrupt
      ? commands.answerInterrupt(message)
      : commands.sendMessage(message, mode, attachments.length > 0 ? attachments : undefined)
    runtimeStore.addUserMessage(message, command.request_id, {
      mode,
      package_id: mode === 'evolve_agent' ? selectedEvolutionPackageId.value : undefined,
      interrupt_resume: runtimeStore.isAwaitingUserInputInterrupt,
    })
    return true
  }

  function cancelRequest() {
    commands.cancelRequest('user_cancelled')
  }

  function applyRouteMode() {
    if (isManufacturingRoute.value) {
      agentStore.leaveAgentChat()
      const shouldSwitchSession = runtimeStore.currentMode !== 'create_agent'
      runtimeStore.enterFactoryConversation('create_agent')
      if (runtimeStore.activeFactorySessionId && shouldSwitchSession) {
        commands.startSession(true, 'create_agent')
      }
      return
    }
    if (isEvolutionRoute.value) {
      agentStore.leaveAgentChat()
      const shouldSwitchSession = runtimeStore.currentMode !== 'evolve_agent'
      runtimeStore.enterFactoryConversation('evolve_agent', agentStore.selectedPackageId)
      if (runtimeStore.activeFactorySessionId && shouldSwitchSession) {
        commands.startSession(true, 'evolve_agent')
      }
      if (agentStore.agentPackages.length === 0) {
        commands.listAgentPackages()
      }
      return
    }
    if (isAgentChatActive.value) return
    if (route.name === 'Factory' && runtimeStore.currentMode !== 'chat') {
      runtimeStore.enterFactoryConversation('chat')
      if (runtimeStore.activeFactorySessionId) {
        commands.startSession(true, 'chat')
      }
    }
  }

  return {
    isAgentChatActive,
    isEvolutionRoute,
    selectedEvolutionPackageId,
    evolutionPackageOptions,
    inputPlaceholder,
    inputDisabled,
    emptyDescription,
    emptyHint,
    applyRouteMode,
    cancelRequest,
    handleEvolutionPackageSelect,
    sendMessage,
  }
}
