import { computed, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute } from 'vue-router'
import {
  isAvailableChatModelProfile,
  modelPoolApi,
  type ModelPoolProfile,
} from '@/api/modelPool'
import { useAgentStore } from '@/stores/agent'
import { useRuntimeStore } from '@/stores/runtime'
import { useUiStore } from '@/stores/ui'
import { useWorkspaceStore } from '@/stores/workspace'
import { useRuntimePreferencesStore } from '@/stores/runtimePreferences'
import { useCommand } from '@/composables/useCommand'
import { useI18n } from '@/composables/useI18n'
import type { FactoryMode, RuntimeAttachmentInput, TranscriptAttachmentView } from '@/types/protocol'
import { isAgentSessionsLanding } from '@/utils/agentSessionRoute'
import { SYSTEM_CHAT_PACKAGE_ID } from '@/utils/resourceScope'

export function useFactoryConversation() {
  const route = useRoute()
  const runtimeStore = useRuntimeStore()
  const agentStore = useAgentStore()
  const uiStore = useUiStore()
  const workspaceStore = useWorkspaceStore()
  const runtimePreferences = useRuntimePreferencesStore()
  const commands = useCommand()
  const { t } = useI18n()
  const chatModelProfiles = ref<ModelPoolProfile[]>([])
  const {
    mainModelProfileId: selectedMainModelProfileId,
    reasoningIntensity,
  } = storeToRefs(runtimePreferences)

  const isAgentChatActive = computed(() => Boolean(agentStore.activeChatPackageId))
  const requiresRuntimeMainModel = computed(() => (
    !agentStore.activeChatPackageId || agentStore.activeChatPackageId === SYSTEM_CHAT_PACKAGE_ID
  ))
  const isAgentSessionLanding = computed(() => (
    route.name === 'Factory' && isAgentSessionsLanding(route.query)
  ))
  const isManufacturingRoute = computed(() => route.name === 'Manufacturing')
  const isEvolutionRoute = computed(() => route.name === 'Evolution')
  const currentFactoryMessageMode = computed<FactoryMode>(() => {
    if (isManufacturingRoute.value) return 'create_agent'
    if (isEvolutionRoute.value) return 'evolve_agent'
    return 'agent_package'
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
  const agentPackageOptions = computed(() => agentStore.agentPackages.map((pkg) => ({
    label: pkg.agent_name || pkg.name || pkg.package_id,
    value: pkg.package_id,
  })))
  const runtimeMainModelOptions = computed(() => [
    ...(isAgentChatActive.value && chatModelProfiles.value.length > 0
      ? [{ label: t('chat.defaultMainModel'), value: '' }]
      : []),
    ...chatModelProfiles.value.map((profile) => ({
      label: profile.display_name || profile.model_name || profile.profile_id,
      value: profile.profile_id,
    })),
  ])
  const inputPlaceholder = computed(() => (
    isAgentChatActive.value
      ? t('factory.sendToAgentPlaceholder', { name: activeChatPackageTitle.value })
      : isAgentSessionLanding.value
        ? t('factory.selectAgentFirst')
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
    || chatModelProfiles.value.length === 0
    || (requiresRuntimeMainModel.value && !selectedMainModelProfileId.value)
    || (isAgentSessionLanding.value && !isAgentChatActive.value)
    || (isEvolutionRoute.value && !selectedEvolutionPackageId.value)
  ))
  const emptyDescription = computed(() => {
    if (isAgentSessionLanding.value) return t('factory.emptyAgentSelection')
    if (isEvolutionRoute.value) return selectedEvolutionPackageId.value ? t('factory.emptyEvolutionReady') : t('factory.emptyEvolutionSelect')
    if (isManufacturingRoute.value) return t('factory.emptyManufacturing')
    return t('factory.emptyChat')
  })
  const emptyHint = computed(() => {
    if (isAgentSessionLanding.value) return t('factory.emptyAgentSelectionHint')
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
      const [response, roleBindingResponse] = await Promise.all([
        modelPoolApi.profiles(),
        modelPoolApi.roleBindings(),
      ])
      chatModelProfiles.value = response.profiles.filter(isAvailableChatModelProfile)
      const configuredMainProfileId = roleBindingResponse.bindings.main
      if (chatModelProfiles.value.some((profile) => profile.profile_id === selectedMainModelProfileId.value)) {
        return
      }
      if (
        configuredMainProfileId
        && chatModelProfiles.value.some((profile) => profile.profile_id === configuredMainProfileId)
      ) {
        setSelectedMainModelProfileId(configuredMainProfileId)
      } else if (!chatModelProfiles.value.some((profile) => profile.profile_id === selectedMainModelProfileId.value)) {
        await selectRecommendedRuntimeMainModel()
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

  async function selectRecommendedRuntimeMainModel() {
    if (chatModelProfiles.value.length === 0) {
      setSelectedMainModelProfileId('')
      return
    }
    const selection = await modelPoolApi.select({
      requirements: [{
        role: 'main',
        purpose: 'Factory runtime main conversation model',
        kind: 'chat',
        input_modalities: ['text'],
        output_modalities: ['text'],
        tool_calling: true,
        structured_output_methods: ['json_mode', 'function_calling'],
        optimize_for: 'balanced',
      }],
    })
    const profileId = String(
      selection.recommendations.find(item => item.role === 'main')?.profile_id || ''
    ).trim()
    setSelectedMainModelProfileId(
      chatModelProfiles.value.some(profile => profile.profile_id === profileId) ? profileId : ''
    )
  }

  function setSelectedMainModelProfileId(profileId: string) {
    runtimePreferences.setMainModelProfileId(profileId)
    const profile = chatModelProfiles.value.find((item) => item.profile_id === profileId)
    if (profile?.capabilities.reasoning_supported === false) {
      runtimePreferences.setReasoningIntensity(null)
    }
  }

  function runtimeModelOptions() {
    const profileId = selectedMainModelProfileId.value.trim()
    return {
      ...(profileId ? { mainModelProfileId: profileId } : {}),
      ...(reasoningIntensity.value !== null ? { reasoningIntensity: reasoningIntensity.value } : {}),
      requestTimeoutSeconds: runtimePreferences.requestTimeoutSeconds,
      maxRetries: runtimePreferences.maxRetries,
    }
  }

  function setReasoningIntensity(value: number | null) {
    runtimePreferences.setReasoningIntensity(value)
  }

  function sendMessage(message: string, attachments: RuntimeAttachmentInput[]): boolean {
    if (chatModelProfiles.value.length === 0) {
      uiStore.addNotification({
        type: 'warning',
        title: t('chat.modelRequiredTitle'),
        message: t('chat.modelRequiredMessage'),
        duration: 4000,
      })
      return false
    }
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
        ...runtimeSelectionMetadata(),
      }, visibleAttachments)
      return true
    }

    if (requiresRuntimeMainModel.value && !selectedMainModelProfileId.value.trim()) {
      uiStore.addNotification({
        type: 'warning',
        title: t('chat.modelRequiredTitle'),
        message: t('chat.modelRequiredMessage'),
        duration: 4000,
      })
      return false
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
        ...runtimeSelectionMetadata(),
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
      ...runtimeSelectionMetadata(),
    }, runtimeStore.isAwaitingUserInputInterrupt ? [] : visibleAttachments)
    return true
  }

  function runtimeSelectionMetadata(): Record<string, string | number> {
    const profileId = selectedMainModelProfileId.value.trim()
    return {
      ...(profileId ? { model_profile_id: profileId } : {}),
      ...(reasoningIntensity.value !== null ? { reasoning_intensity: reasoningIntensity.value } : {}),
    }
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
      runtimeStore.enterFactoryConversation('create_agent')
      commands.startSession(true, 'create_agent')
      return
    }
    if (isEvolutionRoute.value) {
      agentStore.leaveAgentChat()
      const packageId = agentStore.selectedPackageId
      runtimeStore.enterFactoryConversation('evolve_agent', packageId)
      if (packageId) {
        void commands.selectAgentPackage(packageId, 'evolution')
      } else {
        commands.startSession(true, 'evolve_agent')
      }
      if (agentStore.agentPackages.length === 0) {
        commands.listAgentPackages()
      }
      return
    }
  }

  watch(isAgentChatActive, (active) => {
    if (!active && !selectedMainModelProfileId.value && chatModelProfiles.value.length > 0) {
      void selectRecommendedRuntimeMainModel()
    }
  })

  return {
    isAgentChatActive,
    isAgentSessionLanding,
    isEvolutionRoute,
    selectedEvolutionPackageId,
    agentPackageOptions,
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

function attachmentViews(attachments: RuntimeAttachmentInput[]): TranscriptAttachmentView[] {
  return attachments.map((attachment) => ({
    kind: attachment.kind,
    name: attachment.name,
    source_kind: attachment.source_kind,
    mime_type: attachment.mime_type,
  }))
}
