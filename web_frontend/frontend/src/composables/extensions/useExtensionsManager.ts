import { computed, onMounted, ref, watch } from 'vue'
import { useDialog } from 'naive-ui'
import { useCommand } from '@/composables/useCommand'
import { useI18n } from '@/composables/useI18n'
import { useResourceContext } from '@/composables/useResourceContext'
import { useExtensionStore } from '@/stores/extension'
import type { McpServerConfig, SkillConfig } from '@/api/resourceTypes'
import type { ExtensionItemView } from '@/types/protocol'

export function useExtensionsManager() {
  const extensionStore = useExtensionStore()
  const commands = useCommand()
  const dialog = useDialog()
  const resourceContext = useResourceContext()
  const { t } = useI18n()

  const showMcpModal = ref(false)
  const showSkillModal = ref(false)
  const editingMcp = ref<ExtensionItemView | null>(null)
  const editingSkill = ref<ExtensionItemView | null>(null)
  const busyKey = ref<string | null>(null)

  const packageId = computed(() => resourceContext.packageIdForApi.value)
  const activePackageLabel = computed(() => t('resource.currentConfigTarget', { label: resourceContext.label.value }))
  const testResultType = computed(() => (
    extensionStore.testResult?.status === 'ok' ? 'success' : 'error'
  ))
  const testResultTitle = computed(() => (
    extensionStore.testResult?.status === 'ok' ? t('extensions.connectionOk') : t('extensions.connectionFailed')
  ))
  const testResultMessage = computed(() => String(extensionStore.testResult?.message || t('extensions.noTestResult')))
  const testTools = computed(() => (
    Array.isArray(extensionStore.testResult?.tools) ? extensionStore.testResult.tools : []
  ))

  function refreshCurrentExtensions() {
    extensionStore.reset()
    editingMcp.value = null
    editingSkill.value = null
    showMcpModal.value = false
    showSkillModal.value = false
    return commands.refreshExtensions(packageId.value)
  }

  function openAddMcp(): void {
    editingMcp.value = null
    showMcpModal.value = true
  }

  function openEditMcp(item: ExtensionItemView): void {
    editingMcp.value = item
    showMcpModal.value = true
  }

  function openAddSkill(): void {
    editingSkill.value = null
    showSkillModal.value = true
  }

  function openEditSkill(item: ExtensionItemView): void {
    editingSkill.value = item
    showSkillModal.value = true
  }

  async function handleTestMcp(item: ExtensionItemView): Promise<void> {
    const serverId = String(item.payload?.server_id || '')
    if (!serverId) return
    busyKey.value = `test:${extensionKey(item)}`
    try {
      await commands.testMcp(serverId, packageId.value)
    } finally {
      busyKey.value = null
    }
  }

  async function handleToggleMcp(item: ExtensionItemView, enabled: boolean): Promise<void> {
    const serverId = String(item.payload?.server_id || '')
    if (!serverId) return
    busyKey.value = `toggle:${extensionKey(item)}`
    try {
      await commands.setMcpEnabled(serverId, enabled, packageId.value)
    } finally {
      busyKey.value = null
    }
  }

  async function handleToggleSkill(item: ExtensionItemView, enabled: boolean): Promise<void> {
    const skillId = String(item.payload?.skill_id || '')
    if (!skillId) return
    busyKey.value = `toggle:${extensionKey(item)}`
    try {
      await commands.setSkillEnabled(skillId, enabled, packageId.value)
    } finally {
      busyKey.value = null
    }
  }

  async function handleSaveMcp(config: McpServerConfig): Promise<void> {
    const event = await commands.saveMcp(config, packageId.value)
    if (event) {
      showMcpModal.value = false
      editingMcp.value = null
    }
  }

  async function handleSaveSkill(config: SkillConfig): Promise<void> {
    const event = await commands.saveSkill(config, packageId.value)
    if (event) {
      showSkillModal.value = false
      editingSkill.value = null
    }
  }

  function handleMcpAction(key: string, item: ExtensionItemView): void {
    if (key === 'edit') {
      openEditMcp(item)
      return
    }
    if (key === 'remove') {
      confirmRemoveMcp(item)
    }
  }

  function handleSkillAction(key: string, item: ExtensionItemView): void {
    if (key === 'edit') {
      openEditSkill(item)
      return
    }
    if (key === 'remove') {
      confirmRemoveSkill(item)
    }
  }

  function confirmRemoveMcp(item: ExtensionItemView): void {
    const serverId = String(item.payload?.server_id || '')
    if (!serverId) return
    dialog.warning({
      title: t('extensions.deleteMcpTitle'),
      content: t('extensions.deleteMcpContent', { name: item.name || t('extensions.thisMcpServer') }),
      positiveText: t('common.delete'),
      negativeText: t('common.cancel'),
      onPositiveClick: () => {
        void commands.removeMcp(serverId, packageId.value)
      },
    })
  }

  function confirmRemoveSkill(item: ExtensionItemView): void {
    const skillId = String(item.payload?.skill_id || '')
    if (!skillId) return
    dialog.warning({
      title: t('extensions.deleteSkillTitle'),
      content: t('extensions.deleteSkillContent', { name: item.name || t('extensions.thisSkill') }),
      positiveText: t('common.delete'),
      negativeText: t('common.cancel'),
      onPositiveClick: () => {
        void commands.removeSkill(skillId, packageId.value)
      },
    })
  }

  watch(
    () => resourceContext.packageId.value,
    () => {
      void refreshCurrentExtensions()
    },
  )

  onMounted(() => {
    commands.listAgentPackages()
    void refreshCurrentExtensions()
  })

  const mcpActions = computed(() => [
    { label: t('common.edit'), key: 'edit' },
    { label: t('common.delete'), key: 'remove' },
  ])

  const skillActions = computed(() => [
    { label: t('common.edit'), key: 'edit' },
    { label: t('common.delete'), key: 'remove' },
  ])

  function mcpCommandLine(item: ExtensionItemView): string {
    const command = String(item.payload?.command || '')
    const args = Array.isArray(item.payload?.args)
      ? item.payload.args.join(' ')
      : String(item.payload?.args || '')
    return [command, args].filter(Boolean).join(' ') || t('extensions.commandUnset')
  }

  return {
    activePackageLabel,
    busyKey,
    editingMcp,
    editingSkill,
    extensionKey,
    extensionStore,
    handleMcpAction,
    handleSaveMcp,
    handleSaveSkill,
    handleSkillAction,
    handleTestMcp,
    handleToggleMcp,
    handleToggleSkill,
    mcpActions,
    mcpCommandLine,
    openAddMcp,
    openAddSkill,
    refreshCurrentExtensions,
    showMcpModal,
    showSkillModal,
    skillActions,
    testResultMessage,
    testResultTitle,
    testResultType,
    testTools,
  }
}

function extensionKey(item: ExtensionItemView): string {
  return String(item.payload?.server_id || item.payload?.skill_id || item.name || item.kind)
}
