import { computed, onMounted, ref, watch } from 'vue'
import { useDialog } from 'naive-ui'
import { useCommand } from '@/composables/useCommand'
import { useI18n } from '@/composables/useI18n'
import { useManagedResourceContext } from '@/composables/useManagedResourceContext'
import { useExtensionStore } from '@/stores/extension'
import type { McpServerConfig, SkillConfig } from '@/api/resourceTypes'
import type {
  ExtensionItemView,
  ToolPermissionApproval,
  ToolPermissionItemView,
  ToolPermissionMode,
  ToolPermissionOverrideView,
  ToolPermissionPolicyView,
  ToolRiskLevel,
} from '@/types/protocol'

export function useExtensionsManager() {
  const extensionStore = useExtensionStore()
  const commands = useCommand()
  const dialog = useDialog()
  const resourceContext = useManagedResourceContext('system_and_package')
  const { t } = useI18n()

  const showMcpModal = ref(false)
  const showSkillModal = ref(false)
  const editingMcp = ref<ExtensionItemView | null>(null)
  const editingSkill = ref<ExtensionItemView | null>(null)
  const busyKey = ref<string | null>(null)
  const skillHubQuery = ref('')
  const mcpInstallResult = ref<Record<string, any> | null>(null)

  const extensionContext = computed(() => resourceContext.workspaceContext.value)
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
  const toolPermissionPolicy = computed<ToolPermissionPolicyView>(() => (
    extensionStore.toolPermissions?.policy || defaultToolPermissionPolicy()
  ))
  const toolPermissionTools = computed(() => extensionStore.toolPermissions?.tools || [])
  const skillHubItems = computed(() => (
    Array.isArray(extensionStore.skillHubResult?.items) ? extensionStore.skillHubResult.items : []
  ))
  const skillHubCliAvailable = computed(() => extensionStore.skillHubResult?.cli_available === true)
  const skillHubStatusMessage = computed(() => String(
    extensionStore.skillHubResult?.message || t('extensions.skillHubStatusUnknown'),
  ))
  const permissionModeOptions = computed(() => [
    { label: t('permissions.mode.strict'), value: 'strict' },
    { label: t('permissions.mode.allowBelowHigh'), value: 'allow_below_high' },
    { label: t('permissions.mode.allowAll'), value: 'allow_all' },
  ])
  const riskLevelOptions = computed(() => [
    { label: t('permissions.risk.low'), value: 'low' },
    { label: t('permissions.risk.medium'), value: 'medium' },
    { label: t('permissions.risk.high'), value: 'high' },
  ])
  const approvalOptions = computed(() => [
    { label: t('permissions.approval.inherit'), value: 'inherit' },
    { label: t('permissions.approval.allow'), value: 'allow' },
    { label: t('permissions.approval.ask'), value: 'ask' },
    { label: t('permissions.approval.deny'), value: 'deny' },
  ])
  const activePermissionModeLabel = computed(() => {
    const match = permissionModeOptions.value.find((option) => option.value === toolPermissionPolicy.value.mode)
    return match?.label || t('permissions.mode.allowBelowHigh')
  })

  function refreshCurrentExtensions() {
    extensionStore.reset()
    editingMcp.value = null
    editingSkill.value = null
    showMcpModal.value = false
    showSkillModal.value = false
    const refresh = commands.refreshExtensions(extensionContext.value)
    void commands.skillHubStatus(extensionContext.value)
    return refresh
  }

  async function handleSkillHubSearch(): Promise<void> {
    const query = skillHubQuery.value.trim()
    if (!query || busyKey.value) return
    busyKey.value = 'skillhub:search'
    try {
      await commands.searchSkillHub(query, extensionContext.value)
    } finally {
      busyKey.value = null
    }
  }

  async function handleSkillHubInstall(item: any): Promise<void> {
    const skill = String(item?.install_name || item?.skill || item?.name || '').trim()
    if (!skill || busyKey.value) return
    busyKey.value = `skillhub:install:${skill}`
    try {
      const event = await commands.installSkillHubSkill(skill, extensionContext.value)
      if (event) await commands.refreshExtensions(extensionContext.value)
    } finally {
      busyKey.value = null
    }
  }

  function openAddMcp(): void {
    editingMcp.value = null
    mcpInstallResult.value = null
    showMcpModal.value = true
  }

  function openEditMcp(item: ExtensionItemView): void {
    editingMcp.value = item
    mcpInstallResult.value = null
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
      await commands.testMcp(serverId, extensionContext.value)
    } finally {
      busyKey.value = null
    }
  }

  async function handleToggleMcp(item: ExtensionItemView, enabled: boolean): Promise<void> {
    const serverId = String(item.payload?.server_id || '')
    if (!serverId) return
    busyKey.value = `toggle:${extensionKey(item)}`
    try {
      await commands.setMcpEnabled(serverId, enabled, extensionContext.value)
    } finally {
      busyKey.value = null
    }
  }

  async function handleToggleSkill(item: ExtensionItemView, enabled: boolean): Promise<void> {
    const skillId = String(item.payload?.skill_id || '')
    if (!skillId) return
    busyKey.value = `toggle:${extensionKey(item)}`
    try {
      await commands.setSkillEnabled(skillId, enabled, extensionContext.value)
    } finally {
      busyKey.value = null
    }
  }

  async function handleInstallMcp(servers: McpServerConfig[]): Promise<void> {
    if (busyKey.value || servers.length === 0) return
    busyKey.value = 'mcp:install'
    mcpInstallResult.value = null
    try {
      const event = await commands.installMcp(servers, extensionContext.value)
      const install = event?.payload?.install
      mcpInstallResult.value = install && typeof install === 'object' ? install : null
      if (mcpInstallResult.value?.status !== 'ok') return
      showMcpModal.value = false
      editingMcp.value = null
    } finally {
      busyKey.value = null
    }
  }

  async function handleSaveSkill(config: SkillConfig): Promise<void> {
    const event = await commands.saveSkill(config, extensionContext.value)
    if (event) {
      showSkillModal.value = false
      editingSkill.value = null
    }
  }

  async function handlePermissionModeChange(mode: string): Promise<void> {
    const nextMode = normalizePermissionMode(mode)
    busyKey.value = 'tool-permissions:mode'
    try {
      await commands.updateToolPermissions(
        { mode: nextMode, tool_overrides: toolPermissionPolicy.value.tool_overrides || {} },
        extensionContext.value,
      )
    } finally {
      busyKey.value = null
    }
  }

  async function handleToolRiskChange(tool: ToolPermissionItemView, riskLevel: string): Promise<void> {
    const override = toolOverride(tool.tool_id)
    await saveToolOverride(tool.tool_id, { ...override, risk_level: normalizeRiskLevel(riskLevel) })
  }

  async function handleToolApprovalChange(tool: ToolPermissionItemView, approval: string): Promise<void> {
    const override = toolOverride(tool.tool_id)
    await saveToolOverride(tool.tool_id, { ...override, approval: normalizeApproval(approval) })
  }

  async function handleResetToolPermission(tool: ToolPermissionItemView): Promise<void> {
    busyKey.value = `permission:${tool.tool_id}`
    try {
      await commands.resetToolPermission(tool.tool_id, extensionContext.value)
    } finally {
      busyKey.value = null
    }
  }

  async function saveToolOverride(toolId: string, override: ToolPermissionOverrideView): Promise<void> {
    busyKey.value = `permission:${toolId}`
    try {
      await commands.setToolPermission(toolId, override, extensionContext.value)
    } finally {
      busyKey.value = null
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
        void commands.removeMcp(serverId, extensionContext.value)
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
        void commands.removeSkill(skillId, extensionContext.value)
      },
    })
  }

  watch(
    () => resourceContext.workspaceContextKey.value,
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
    const url = String(item.payload?.url || '')
    if (url) return url
    const command = String(item.payload?.command || '')
    const args = Array.isArray(item.payload?.args)
      ? item.payload.args.join(' ')
      : String(item.payload?.args || '')
    return [command, args].filter(Boolean).join(' ') || t('extensions.commandUnset')
  }

  function toolOverride(toolId: string): ToolPermissionOverrideView {
    return toolPermissionPolicy.value.tool_overrides?.[toolId] || { approval: 'inherit', risk_level: null }
  }

  function toolRiskValue(tool: ToolPermissionItemView): ToolRiskLevel {
    return toolOverride(tool.tool_id).risk_level || tool.risk_level
  }

  function toolApprovalValue(tool: ToolPermissionItemView): ToolPermissionApproval {
    return toolOverride(tool.tool_id).approval || 'inherit'
  }

  function hasToolOverride(tool: ToolPermissionItemView): boolean {
    return Boolean(toolPermissionPolicy.value.tool_overrides?.[tool.tool_id])
  }

  function toolSourceLabel(source: string): string {
    if (source === 'system') return t('permissions.source.system')
    if (source === 'extension') return t('permissions.source.extension')
    if (source === 'model') return t('permissions.source.model')
    return t('permissions.source.package')
  }

  return {
    activePermissionModeLabel,
    busyKey,
    editingMcp,
    editingSkill,
    extensionKey,
    extensionStore,
    resourceContext,
    handleMcpAction,
    handleInstallMcp,
    handleSaveSkill,
    handleSkillHubInstall,
    handleSkillHubSearch,
    handleSkillAction,
    handleTestMcp,
    handleToggleMcp,
    handleToggleSkill,
    mcpActions,
    mcpCommandLine,
    mcpInstallResult,
    openAddMcp,
    openAddSkill,
    permissionModeOptions,
    refreshCurrentExtensions,
    approvalOptions,
    handlePermissionModeChange,
    handleResetToolPermission,
    handleToolApprovalChange,
    handleToolRiskChange,
    hasToolOverride,
    riskLevelOptions,
    showMcpModal,
    showSkillModal,
    skillActions,
    skillHubCliAvailable,
    skillHubItems,
    skillHubQuery,
    skillHubStatusMessage,
    toolApprovalValue,
    toolPermissionPolicy,
    toolPermissionTools,
    toolRiskValue,
    toolSourceLabel,
    testResultMessage,
    testResultTitle,
    testResultType,
    testTools,
  }
}

function extensionKey(item: ExtensionItemView): string {
  return String(item.payload?.server_id || item.payload?.skill_id || item.name || item.kind)
}

function defaultToolPermissionPolicy(): ToolPermissionPolicyView {
  return {
    mode: 'allow_below_high',
    low: 'allow',
    medium: 'allow',
    high: 'ask',
    tool_overrides: {},
  }
}

function normalizePermissionMode(value: string): ToolPermissionMode {
  if (value === 'strict' || value === 'allow_all' || value === 'custom') return value
  return 'allow_below_high'
}

function normalizeRiskLevel(value: string): ToolRiskLevel {
  if (value === 'medium' || value === 'high') return value
  return 'low'
}

function normalizeApproval(value: string): ToolPermissionApproval {
  if (value === 'allow' || value === 'ask' || value === 'deny') return value
  return 'inherit'
}
