import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { modelPoolApi, type ModelPoolProfile } from '@/api/modelPool'
import { useAgentStore } from '@/stores/agent'
import { useRuntimeStore } from '@/stores/runtime'
import { useUiStore } from '@/stores/ui'
import { useWorkspaceStore } from '@/stores/workspace'
import { useCommand } from '@/composables/useCommand'
import { useI18n } from '@/composables/useI18n'
import type { FactoryMode, RuntimeAttachmentInput, TranscriptAttachmentView } from '@/types/protocol'
import { REASONING_INTENSITY_MAX } from '@/utils/reasoning'

const MAIN_MODEL_PROFILE_STORAGE_KEY = 'fastagentfactory.runtimeMainModelProfileId'
const REASONING_INTENSITY_STORAGE_KEY = 'fastagentfactory.runtimeReasoningIntensity'

export function useFactoryConversation() {
  const route = useRoute()
  const runtimeStore = useRuntimeStore()
  const agentStore = useAgentStore()
  const uiStore = useUiStore()
  const workspaceStore = useWorkspaceStore()
  const commands = useCommand()
  const { t } = useI18n()
  const chatModelProfiles = ref<ModelPoolProfile[]>([])
  const selectedMainModelProfileId = ref(localStorage.getItem(MAIN_MODEL_PROFILE_STORAGE_KEY) || '')
  const reasoningIntensity = ref<number | null>(loadReasoningIntensity())

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
    return pkg?.agent_name || pkg?.name || t('common.unnamedAgent')
  })
  const selectedEvolutionPackageId = computed(() => (
    isEvolutionRoute.value ? agentStore.selectedPackageId : null
  ))
  const selectedEvolutionPackageTitle = computed(() => {
    const pkg = agentStore.selectedPackage
    return pkg?.agent_name || pkg?.name || t('common.current')
  })
  const evolutionPackageOptions = computed(() => agentStore.agentPackages.map((pkg) => ({
    label: pkg.agent_name || pkg.name || pkg.package_id,
    value: pkg.package_id,
  })))
  const runtimeMainModelOptions = computed(() => [
    { label: t('chat.defaultMainModel'), value: '' },
    ...chatModelProfiles.value.map((profile) => ({
      label: profile.display_name || profile.model_name || profile.profile_id,
      value: profile.profile_id,
    })),
  ])
  const inputPlaceholder = computed(() => (
    isAgentChatActive.value
      ? t('factory.sendToAgentPlaceholder', { name: activeChatPackageTitle.value })
      : currentFactoryMessageMode.value === 'create_agent'
        ? t('factory.createAgentPlaceholder')
        : currentFactoryMessageMode.value === 'evolve_agent'
          ? selectedEvolutionPackageId.value
            ? t('factory.evolveAgentPlaceholder', { name: selectedEvolutionPackageTitle.value })
            : t('factory.selectEvolutionFirst')
          : t('chat.inputPlaceholder')
  ))
  const inputDisabled = computed(() => (
    runtimeStore.isInputLocked
    || runtimeStore.isPublishConfirmationPending
    || (isEvolutionRoute.value && !selectedEvolutionPackageId.value)
  ))
  const emptyDescription = computed(() => {
    if (isEvolutionRoute.value) return selectedEvolutionPackageId.value ? t('factory.emptyEvolutionReady') : t('factory.emptyEvolutionSelect')
    if (isManufacturingRoute.value) return t('factory.emptyManufacturing')
    return t('factory.emptyChat')
  })
  const emptyHint = computed(() => {
    if (isEvolutionRoute.value) {
      return selectedEvolutionPackageId.value
        ? t('factory.emptyEvolutionHint')
        : t('factory.emptyEvolutionSelectHint')
    }
    return t('factory.emptyChatHint')
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

  async function loadRuntimeMainModelProfiles() {
    try {
      const response = await modelPoolApi.profiles()
      chatModelProfiles.value = response.profiles.filter((profile) => (
        profile.kind === 'chat' && profile.enabled && profile.credential?.enabled !== false
      ))
      if (
        selectedMainModelProfileId.value
        && !chatModelProfiles.value.some((profile) => profile.profile_id === selectedMainModelProfileId.value)
      ) {
        setSelectedMainModelProfileId('')
      }
    } catch (error) {
      uiStore.addNotification({
        type: 'warning',
        title: t('modelPool.loadFailedTitle'),
        message: error instanceof Error ? error.message : String(error),
        duration: 3000,
      })
    }
  }

  function setSelectedMainModelProfileId(profileId: string) {
    selectedMainModelProfileId.value = profileId
    if (profileId) {
      localStorage.setItem(MAIN_MODEL_PROFILE_STORAGE_KEY, profileId)
    } else {
      localStorage.removeItem(MAIN_MODEL_PROFILE_STORAGE_KEY)
    }
  }

  function runtimeModelOptions() {
    const profileId = selectedMainModelProfileId.value.trim()
    if (!profileId && reasoningIntensity.value === null) return undefined
    return {
      ...(profileId ? { mainModelProfileId: profileId } : {}),
      ...(reasoningIntensity.value !== null ? { reasoningIntensity: reasoningIntensity.value } : {}),
    }
  }

  function setReasoningIntensity(value: number | null) {
    if (value === null) {
      reasoningIntensity.value = null
      localStorage.removeItem(REASONING_INTENSITY_STORAGE_KEY)
      return
    }
    const normalized = Math.max(0, Math.min(REASONING_INTENSITY_MAX, Math.round(value)))
    reasoningIntensity.value = normalized
    localStorage.setItem(REASONING_INTENSITY_STORAGE_KEY, String(normalized))
  }

  function sendMessage(message: string, attachments: RuntimeAttachmentInput[]): boolean {
    const payloadAttachments = attachments.length > 0 ? attachments : undefined
    const visibleAttachments = attachmentViews(attachments)
    const packageId = agentStore.activeChatPackageId
    if (packageId) {
      const agentSessionId = agentStore.selectedSessionId || undefined
      const command = commands.sendAgentPackageMessage(
        packageId,
        message,
        agentSessionId,
        payloadAttachments,
        runtimeModelOptions()
      )
      runtimeStore.addUserMessage(message, command.request_id, {
        mode: 'agent_package',
        package_id: packageId,
        agent_session_id: agentSessionId || null,
      }, visibleAttachments)
      return true
    }

    const mode = currentFactoryMessageMode.value
    if (mode === 'evolve_agent' && !runtimeStore.isAwaitingUserInputInterrupt) {
      const evolutionPackageId = selectedEvolutionPackageId.value
      if (!evolutionPackageId) {
        uiStore.addNotification({
          type: 'warning',
          title: t('factory.selectEvolutionNotificationTitle'),
          message: t('factory.selectEvolutionNotificationMessage'),
          duration: 3000,
        })
        return false
      }
      const command = commands.runAgentEvolution(evolutionPackageId, message, payloadAttachments, runtimeModelOptions())
      runtimeStore.addUserMessage(message, command.request_id, {
        mode,
        package_id: evolutionPackageId,
      }, visibleAttachments)
      return true
    }

    const command = runtimeStore.isAwaitingUserInputInterrupt
      ? commands.answerInterrupt(message)
      : commands.sendMessage(message, mode, payloadAttachments, runtimeModelOptions())
    runtimeStore.addUserMessage(message, command.request_id, {
      mode,
      package_id: mode === 'evolve_agent' ? selectedEvolutionPackageId.value : undefined,
      interrupt_resume: runtimeStore.isAwaitingUserInputInterrupt,
    }, runtimeStore.isAwaitingUserInputInterrupt ? [] : visibleAttachments)
    return true
  }

  function cancelRequest() {
    const requestId = runtimeStore.activeRequestId
    const visibleOutput = runtimeStore.activeVisibleAssistantOutput
    runtimeStore.markActiveRequestStopping(requestId)
    commands.cancelRequest('user_cancelled', requestId, visibleOutput)
  }

  function applyRouteMode() {
    if (isManufacturingRoute.value) {
      agentStore.leaveAgentChat()
      const shouldSwitchSession = runtimeStore.currentMode !== 'create_agent'
        || runtimeStore.isCollaborationConversationActive
      runtimeStore.enterFactoryConversation('create_agent')
      if (shouldSwitchSession) {
        commands.startSession(true, 'create_agent')
      }
      return
    }
    if (isEvolutionRoute.value) {
      agentStore.leaveAgentChat()
      const packageId = agentStore.selectedPackageId
      const shouldSwitchSession = runtimeStore.currentMode !== 'evolve_agent'
        || runtimeStore.isCollaborationConversationActive
      runtimeStore.enterFactoryConversation('evolve_agent', packageId)
      if (packageId) {
        void commands.selectAgentPackage(packageId, 'evolution')
      } else if (shouldSwitchSession) {
        commands.startSession(true, 'evolve_agent')
      }
      if (agentStore.agentPackages.length === 0) {
        commands.listAgentPackages()
      }
      return
    }
    if (route.name === 'Factory' && runtimeStore.isCollaborationConversationActive) {
      agentStore.leaveAgentChat()
      runtimeStore.enterFactoryConversation('chat')
      commands.startSession(true, 'chat')
      return
    }
    if (isAgentChatActive.value) return
    if (route.name === 'Factory' && runtimeStore.currentMode !== 'chat') {
      runtimeStore.enterFactoryConversation('chat')
      commands.startSession(true, 'chat')
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
    loadRuntimeMainModelProfiles,
    runtimeMainModelOptions,
    reasoningIntensity,
    selectedMainModelProfileId,
    sendMessage,
    setSelectedMainModelProfileId,
    setReasoningIntensity,
  }
}

function loadReasoningIntensity(): number | null {
  const stored = localStorage.getItem(REASONING_INTENSITY_STORAGE_KEY)
  if (stored === null) return null
  const value = Number(stored)
  return Number.isInteger(value) && value >= 0 && value <= REASONING_INTENSITY_MAX ? value : null
}

function attachmentViews(attachments: RuntimeAttachmentInput[]): TranscriptAttachmentView[] {
  return attachments.map((attachment) => ({
    kind: attachment.kind,
    name: attachment.name,
    source_kind: attachment.source_kind,
    mime_type: attachment.mime_type,
  }))
}
