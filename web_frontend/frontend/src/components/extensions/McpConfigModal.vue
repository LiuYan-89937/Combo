<template>
  <n-modal
    v-model:show="show"
    preset="card"
    :title="modalTitle"
    :mask-closable="!busy"
    :closable="!busy"
    style="width: min(900px, calc(100vw - 32px))"
  >
    <div class="install-steps" aria-label="MCP connection workflow">
      <div v-for="step in workflowSteps" :key="step.key" :class="step.state">
        <i>{{ step.state === 'done' ? '✓' : step.number }}</i>
        <span><strong>{{ step.label }}</strong><small>{{ step.description }}</small></span>
      </div>
    </div>

    <div v-if="!item" class="mode-switch">
      <n-radio-group v-model:value="mode" size="small" class="soft-segmented-control">
        <n-radio-button value="import">{{ t('extensions.mcpImportMode') }}</n-radio-button>
        <n-radio-button value="manual">{{ t('extensions.mcpManualMode') }}</n-radio-button>
      </n-radio-group>
    </div>

    <n-spin :show="Boolean(item && editConfigLoading)">
      <section v-if="mode === 'import'" class="import-panel">
        <n-text depth="3">
          {{ item ? t('extensions.mcpEditJsonHint') : t('extensions.mcpImportHint') }}
        </n-text>
        <n-input
          v-model:value="importText"
          type="textarea"
          :rows="14"
          :placeholder="t('extensions.mcpImportPlaceholder')"
        />
        <n-space v-if="!item" justify="end">
          <n-button @click="parseImport">{{ t('extensions.parseConfig') }}</n-button>
        </n-space>
        <n-alert v-if="importErrors.length" type="error" :title="t('extensions.configInvalid')">
          <div v-for="error in importErrors" :key="error">{{ error }}</div>
        </n-alert>
        <div v-if="!item && importedServers.length" class="preview-list">
          <n-text strong>{{ t('extensions.parsePreview') }}</n-text>
          <div v-for="server in importedServers" :key="server.server_id" class="preview-card">
            <div class="preview-heading">
              <n-text strong>{{ server.display_name }}</n-text>
              <n-tag size="small" :bordered="false">{{ server.transport }}</n-tag>
            </div>
            <n-text depth="3" class="preview-command">{{ serverCommand(server) }}</n-text>
            <div class="preview-meta">
              <span v-if="server.transport === 'stdio'">
                {{ t('extensions.envKeys') }}：{{ recordKeys(server.env) || '—' }}
              </span>
              <span v-else>
                {{ t('extensions.headers') }}：{{ recordKeys(server.headers) || '—' }}
              </span>
            </div>
          </div>
        </div>
      </section>

      <n-form v-else ref="formRef" :model="formData" :rules="rules" label-placement="top">
        <n-grid :cols="2" :x-gap="16">
          <n-form-item-gi :label="t('common.name')" path="display_name">
            <n-input v-model:value="formData.display_name" :placeholder="t('extensions.serverName')" />
          </n-form-item-gi>
          <n-form-item-gi :label="t('extensions.transport')">
            <n-select v-model:value="formData.transport" :options="transportOptions" />
          </n-form-item-gi>
        </n-grid>

        <n-form-item :label="t('common.description')">
          <n-input v-model:value="formData.description" type="textarea" :rows="2" />
        </n-form-item>

        <template v-if="formData.transport === 'stdio'">
          <n-form-item :label="t('extensions.command')" path="command">
            <n-input v-model:value="formData.command" placeholder="npx" />
          </n-form-item>
          <n-form-item :label="t('extensions.arguments')">
            <n-input v-model:value="formData.args" placeholder="-y @modelcontextprotocol/server-filesystem" />
          </n-form-item>
          <n-form-item :label="t('extensions.cwd')">
            <n-input v-model:value="formData.cwd" :placeholder="t('extensions.cwdPlaceholder')" />
          </n-form-item>
          <n-form-item :label="t('extensions.env')">
            <n-input v-model:value="formData.env" type="textarea" :rows="3" placeholder="KEY=value" />
          </n-form-item>
        </template>

        <template v-else>
          <n-form-item label="URL" path="url">
            <n-input v-model:value="formData.url" placeholder="https://example.com/mcp" />
          </n-form-item>
          <n-form-item :label="t('extensions.headers')">
            <n-input v-model:value="formData.headers" type="textarea" :rows="3" placeholder="Authorization=Bearer ..." />
          </n-form-item>
        </template>

        <section class="policy-section">
          <div class="section-copy">
            <strong>连接与执行策略</strong>
            <span>连接限制约束服务发现过程，并作为该服务下工具的默认策略。</span>
          </div>
          <n-grid :cols="2" :x-gap="16">
            <n-form-item-gi label="连接超时（秒）">
              <n-input-number v-model:value="formData.connect_timeout_seconds" :min="1" :max="300" />
            </n-form-item-gi>
            <n-form-item-gi :label="t('extensions.toolCallTimeoutSeconds')">
              <n-input-number v-model:value="formData.timeout_seconds" :min="1" :max="3600" />
            </n-form-item-gi>
            <n-form-item-gi label="最大并发请求数">
              <n-input-number v-model:value="formData.max_parallel_requests" :min="1" :max="128" />
            </n-form-item-gi>
            <n-form-item-gi :label="t('permissions.riskLevel')">
              <n-select v-model:value="formData.risk_level_default" :options="riskOptions" />
            </n-form-item-gi>
          </n-grid>
          <div class="switch-row">
            <span><strong>发现的工具默认允许并发</strong><small>每个工具仍可在 Tool 池中单独覆盖。</small></span>
            <n-switch v-model:value="formData.concurrent_default" />
          </div>
        </section>
      </n-form>
    </n-spin>

    <section v-if="installResult" class="install-console" :class="String(installResult.status || '')">
      <header>
        <div>
          <span class="console-kicker">MCP CONNECTION</span>
          <strong>{{ installResultTitle }}</strong>
        </div>
        <n-tag size="small" :type="installResultType" :bordered="false">{{ installStatusLabel }}</n-tag>
      </header>
      <div v-if="installLogs.length" class="install-timeline">
        <div v-for="(entry, index) in installLogs" :key="`${entry.stage}-${index}`" class="install-event">
          <i />
          <div>
            <strong>{{ stageLabel(entry.stage) }}</strong>
            <span>{{ stageDetail(entry) }}</span>
          </div>
        </div>
      </div>
      <p v-if="installResult.error" class="install-error">{{ installResult.error }}</p>
      <div v-for="test in installResult.tests || []" :key="test.server_id" class="test-row">
        <div class="test-heading">
          <strong>{{ test.server_id }}</strong>
          <n-tag
            size="small"
            :type="test.status === 'ok' ? 'success' : test.status === 'running' ? 'info' : test.status === 'cancelled' ? 'warning' : 'error'"
            :bordered="false"
          >
            {{ testStatusLabel(test.status) }}
          </n-tag>
        </div>
        <McpTestResultDetails :result="test" />
      </div>
    </section>

    <template #footer>
      <n-space justify="space-between">
        <n-text depth="3">{{ t('extensions.mcpInstallNotice') }}</n-text>
        <n-space>
          <n-button
            v-if="busy"
            type="error"
            secondary
            :loading="stopping"
            :disabled="stopping"
            @click="emit('cancel-install')"
          >
            {{ stopping ? t('extensions.mcpInstallStopping') : t('extensions.stopMcpInstall') }}
          </n-button>
          <n-button v-else @click="show = false">{{ t('common.cancel') }}</n-button>
          <n-button
            type="primary"
            :loading="busy"
            :disabled="busy || Boolean(item && editConfigLoading)"
            @click="handleSubmit"
          >
            {{ item ? t('extensions.testAndSave') : t('extensions.testAndAdd') }}
          </n-button>
        </n-space>
      </n-space>
    </template>
  </n-modal>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  NAlert,
  NButton,
  NForm,
  NFormItem,
  NFormItemGi,
  NGrid,
  NInput,
  NInputNumber,
  NModal,
  NRadioButton,
  NRadioGroup,
  NSelect,
  NSpace,
  NSpin,
  NSwitch,
  NTag,
  NText,
} from 'naive-ui'
import type { FormInst, FormRules } from 'naive-ui'
import type { McpServerConfig } from '@/api/resourceTypes'
import type { ExtensionItemView } from '@/types/protocol'
import { useI18n } from '@/composables/useI18n'
import { requiredTextRule } from '@/utils/formValidation'
import McpTestResultDetails from './McpTestResultDetails.vue'
import {
  mcpConfigArgsText,
  mcpConfigRecordText,
  parseMcpConfigText,
  type McpConfigParserMessages,
} from './mcpConfigParser'

const props = withDefaults(defineProps<{
  show: boolean
  item?: ExtensionItemView | null
  editConfig?: Record<string, unknown> | null
  editConfigLoading?: boolean
  busy?: boolean
  stopping?: boolean
  installResult?: any | null
}>(), {
  busy: false,
  stopping: false,
  installResult: null,
  editConfig: null,
  editConfigLoading: false,
})

const emit = defineEmits<{
  'update:show': [value: boolean]
  submit: [servers: McpServerConfig[]]
  'cancel-install': []
}>()

const show = computed({ get: () => props.show, set: value => emit('update:show', value) })
const { t } = useI18n()
const mcpParserMessages = computed<McpConfigParserMessages>(() => ({
  emptyConfig: t('extensions.mcpImportEmpty'),
  jsonParseFailed: reason => t('extensions.mcpJsonParseFailed', { reason }),
  noRecognizedServers: t('extensions.mcpNoRecognizedServers'),
  serverEntryName: index => t('extensions.mcpServerEntryName', { index }),
  invalidServer: (name, reason) => t('extensions.mcpServerEntryInvalid', { name, reason }),
  duplicateServerIds: ids => t('extensions.mcpDuplicateServerIds', { ids }),
  stdioCommandRequired: t('extensions.mcpStdioCommandRequired'),
  transportUrlRequired: transport => t('extensions.mcpTransportUrlRequired', { transport }),
  unsupportedTransport: transport => t('extensions.mcpUnsupportedTransport', { transport }),
}))
const formRef = ref<FormInst | null>(null)
const mode = ref<'import' | 'manual'>('import')
const importText = ref('')
const importErrors = ref<string[]>([])
const importedServers = ref<McpServerConfig[]>([])
const modalTitle = computed(() => props.item ? t('extensions.mcpEditTitle') : t('extensions.mcpAddTitle'))
const installResultType = computed(() => {
  if (props.installResult?.status === 'ok') return 'success'
  if (props.installResult?.status === 'running') return 'info'
  if (props.installResult?.status === 'cancelled') return 'warning'
  return 'error'
})
const installLogs = computed<Array<{ stage: string; detail: Record<string, unknown> }>>(() => (
  Array.isArray(props.installResult?.logs) ? props.installResult.logs : []
))
const installResultTitle = computed(() => {
  if (props.installResult?.status === 'ok') return t('extensions.mcpPublishSucceeded')
  if (props.installResult?.status === 'cancelled') return t('extensions.mcpInstallCancelled')
  if (props.installResult?.status === 'failed') return t('extensions.connectionFailed')
  return stageLabel(String(props.installResult?.stage || 'validating'))
})
const installStatusLabel = computed(() => {
  if (props.installResult?.status === 'ok') return t('extensions.mcpInstallSucceeded')
  if (props.installResult?.status === 'cancelled') return t('extensions.mcpInstallCancelled')
  if (props.installResult?.status === 'failed') return t('extensions.connectionFailed')
  return t('extensions.mcpInstallRunning')
})
const workflowSteps = computed(() => {
  const order = ['configure', 'connect', 'discover', 'publish']
  const current = workflowIndex(String(props.installResult?.stage || 'configure'))
  const labels = [
    [t('extensions.mcpStepConfigure'), t('extensions.mcpStepConfigureHint')],
    [t('extensions.mcpStepConnect'), t('extensions.mcpStepConnectHint')],
    [t('extensions.mcpStepDiscover'), t('extensions.mcpStepDiscoverHint')],
    [t('extensions.mcpStepPublish'), t('extensions.mcpStepPublishHint')],
  ]
  return order.map((key, index) => ({
    key,
    number: index + 1,
    label: labels[index][0],
    description: labels[index][1],
    state: props.installResult?.status === 'ok' || index < current ? 'done' : index === current ? 'active' : 'pending',
  }))
})
const formData = ref(emptyForm())

const transportOptions = computed(() => [
  { label: 'stdio', value: 'stdio' },
  { label: 'Streamable HTTP', value: 'streamable_http' },
  { label: 'SSE', value: 'sse' },
])
const riskOptions = computed(() => [
  { label: t('permissions.risk.low'), value: 'low' },
  { label: t('permissions.risk.medium'), value: 'medium' },
  { label: t('permissions.risk.high'), value: 'high' },
])
const rules = computed<FormRules>(() => ({
  display_name: [requiredTextRule(t('extensions.validateName'))],
  command: [{
    required: formData.value.transport === 'stdio',
    validator: () => formData.value.transport !== 'stdio' || Boolean(formData.value.command.trim()),
    message: t('extensions.validateCommand'),
    trigger: ['input', 'blur'],
  }],
  url: [{
    required: formData.value.transport !== 'stdio',
    validator: () => formData.value.transport === 'stdio' || /^https?:\/\//.test(formData.value.url.trim()),
    message: t('extensions.validateUrl'),
    trigger: ['input', 'blur'],
  }],
}))

function emptyForm() {
  return {
    display_name: '', description: '', transport: 'stdio' as McpServerConfig['transport'],
    command: '', args: '', cwd: '', env: '', url: '', headers: '', timeout_seconds: 60,
    connect_timeout_seconds: 30, max_parallel_requests: 1, concurrent_default: true,
    risk_level_default: 'medium' as NonNullable<McpServerConfig['risk_level_default']>,
  }
}

function loadForm(item: ExtensionItemView | null | undefined) {
  formData.value = emptyForm()
  if (!item) return
  const payload = props.editConfig || item.payload || {}
  const source = payload.source && typeof payload.source === 'object'
    ? payload.source as Record<string, unknown>
    : {}
  formData.value = {
    display_name: String(payload.display_name || source.name || item.name || ''),
    description: String(payload.description || source.description || ''),
    transport: normalizeTransport(payload.transport),
    command: String(payload.command || ''),
    args: mcpConfigArgsText(payload.args),
    cwd: String(payload.cwd || ''), env: bindingText(payload.env), url: String(payload.url || ''), headers: bindingText(payload.headers),
    timeout_seconds: Number(payload.timeout_seconds || 60),
    connect_timeout_seconds: Number(payload.connect_timeout_seconds || 30),
    max_parallel_requests: Number(payload.max_parallel_requests || 1),
    concurrent_default: payload.concurrent_default !== false,
    risk_level_default: normalizeRiskLevel(payload.risk_level_default),
  }
}

watch(() => props.show, (visible) => {
  if (!visible) return
  mode.value = props.item ? 'manual' : 'import'
  importText.value = ''
  importErrors.value = []
  importedServers.value = []
  loadForm(props.item)
  loadEditConfig()
})
watch(() => props.item, item => { if (props.show) loadForm(item) })
watch(() => props.editConfig, () => {
  if (props.show && props.item) loadEditConfig()
})

function loadEditConfig() {
  if (!props.item || !props.editConfig) return
  importText.value = JSON.stringify(props.editConfig, null, 2)
  loadForm(props.item)
}

function parseImport() {
  const result = parseMcpConfigText(importText.value, mcpParserMessages.value)
  importedServers.value = result.servers
  importErrors.value = result.errors
}

function handleSubmit() {
  if (mode.value === 'import' && props.item) {
    const server = parseEditedServer()
    if (server) emit('submit', [server])
    return
  }
  if (mode.value === 'import') {
    parseImport()
    if (!importedServers.value.length || importErrors.value.length) return
    emit('submit', importedServers.value)
    return
  }
  formRef.value?.validate((errors) => {
    if (errors) return
    emit('submit', [manualServer()])
  })
}

function parseEditedServer(): McpServerConfig | null {
  importErrors.value = []
  let decoded: unknown
  try {
    decoded = JSON.parse(importText.value)
  } catch (error) {
    importErrors.value = [mcpParserMessages.value.jsonParseFailed(
      error instanceof Error ? error.message : String(error),
    )]
    return null
  }
  if (!decoded || typeof decoded !== 'object' || Array.isArray(decoded)) {
    importErrors.value = [t('extensions.mcpEditJsonObjectRequired')]
    return null
  }
  const server = { ...(decoded as Record<string, unknown>) }
  const source = server.source && typeof server.source === 'object'
    ? server.source as Record<string, unknown>
    : {}
  server.server_id = String(props.item?.payload?.server_id || server.server_id || '')
  server.display_name = String(props.item?.payload?.display_name || server.display_name || source.name || '')
  server.description = String(props.item?.payload?.description || server.description || source.description || '')
  return server as unknown as McpServerConfig
}

function manualServer(): McpServerConfig {
  const name = formData.value.display_name.trim()
  const env = formData.value.env.trim()
  const headers = formData.value.headers.trim()
  return {
    server_id: props.item?.payload?.server_id,
    display_name: name,
    description: formData.value.description.trim(),
    transport: formData.value.transport,
    command: formData.value.transport === 'stdio' ? formData.value.command.trim() : undefined,
    args: formData.value.transport === 'stdio' ? formData.value.args.trim() : undefined,
    cwd: formData.value.transport === 'stdio' ? formData.value.cwd.trim() : undefined,
    env: formData.value.transport === 'stdio' && env ? bindingRecordInput(env, props.editConfig?.env) : undefined,
    url: formData.value.transport !== 'stdio' ? formData.value.url.trim() : undefined,
    headers: formData.value.transport !== 'stdio' && headers ? bindingRecordInput(headers, props.editConfig?.headers) : undefined,
    timeout_seconds: formData.value.timeout_seconds,
    connect_timeout_seconds: formData.value.connect_timeout_seconds,
    max_parallel_requests: formData.value.max_parallel_requests,
    concurrent_default: formData.value.concurrent_default,
    enabled: true,
    risk_level_default: formData.value.risk_level_default,
    source: { type: formData.value.transport === 'stdio' ? 'local' : 'remote', name, description: formData.value.description.trim() || undefined },
  }
}

function normalizeTransport(value: unknown): McpServerConfig['transport'] {
  if (value === 'streamable_http' || value === 'sse') return value
  return 'stdio'
}

function normalizeRiskLevel(value: unknown): NonNullable<McpServerConfig['risk_level_default']> {
  if (value === 'low' || value === 'high') return value
  return 'medium'
}

function serverCommand(server: McpServerConfig): string {
  return server.transport === 'stdio'
    ? [server.command, mcpConfigArgsText(server.args)].filter(Boolean).join(' ')
    : String(server.url || '')
}

function recordKeys(value: McpServerConfig['env']): string {
  const text = mcpConfigRecordText(value)
  return text.split('\n').map(line => line.split('=', 1)[0]?.trim()).filter(Boolean).join(', ')
}

function bindingText(value: unknown): string {
  if (typeof value === 'string') return value
  if (!value || typeof value !== 'object' || Array.isArray(value)) return ''
  return Object.entries(value as Record<string, unknown>).map(([target, raw]) => {
    if (typeof raw === 'string') return `${target}=${raw}`
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return `${target}=`
    const reference = raw as Record<string, unknown>
    return reference.source === 'process_environment'
      ? `${target}=${String(reference.name || '')}`
      : `${target}=${String(reference.value || '')}`
  }).join('\n')
}

function bindingRecordInput(text: string, original: unknown): Record<string, any> {
  const previous = original && typeof original === 'object' && !Array.isArray(original)
    ? original as Record<string, unknown>
    : {}
  return Object.fromEntries(text.split(/\r?\n/).map(line => line.trim()).filter(Boolean).map((line) => {
    const separator = line.indexOf('=')
    const target = (separator < 0 ? line : line.slice(0, separator)).trim()
    const value = (separator < 0 ? target : line.slice(separator + 1)).trim()
    const existing = previous[target]
    const processEnvironment = existing && typeof existing === 'object' && !Array.isArray(existing)
      && (existing as Record<string, unknown>).source === 'process_environment'
    return [target, processEnvironment
      ? { source: 'process_environment', name: value }
      : { source: 'literal', value }]
  }))
}

function testStatusLabel(status: unknown): string {
  if (status === 'ok') return t('extensions.connectionOk')
  if (status === 'running') return t('extensions.mcpInstallRunning')
  if (status === 'cancelled') return t('extensions.mcpInstallCancelled')
  return t('extensions.connectionFailed')
}

function workflowIndex(stage: string): number {
  if (stage === 'published') return 3
  if (stage === 'catalog_discovered' || stage === 'tools_discovered' || stage === 'capabilities_prepared') return 2
  if (stage === 'connecting' || stage === 'initialized') return 1
  return 0
}

function stageLabel(stage: string): string {
  const labels: Record<string, string> = {
    validating: t('extensions.mcpStageValidating'),
    connecting: t('extensions.mcpStageConnecting'),
    initialized: t('extensions.mcpStageInitialized'),
    tools_discovered: t('extensions.mcpStageToolsDiscovered'),
    catalog_discovered: t('extensions.mcpStageCatalogDiscovered'),
    capabilities_prepared: t('extensions.mcpStageCapabilitiesPrepared'),
    published: t('extensions.mcpStagePublished'),
  }
  return labels[stage] || stage
}

function stageDetail(entry: { stage: string; detail: Record<string, unknown> }): string {
  const detail = entry.detail || {}
  if (entry.stage === 'connecting') return String(detail.transport || '')
  if (entry.stage === 'initialized') {
    const server = [detail.server_name, detail.server_version].filter(Boolean).join(' ')
    const protocol = detail.protocol_version ? `MCP ${detail.protocol_version}` : ''
    const capabilities = Array.isArray(detail.capabilities) ? detail.capabilities.join(' · ') : ''
    return [server, protocol, capabilities].filter(Boolean).join(' · ')
  }
  if (entry.stage === 'catalog_discovered' || entry.stage === 'tools_discovered' || entry.stage === 'capabilities_prepared') {
    return t('extensions.mcpDiscoveredCatalogCounts', {
      tools: Number(detail.tool_count || 0),
      resources: Number(detail.resource_count || 0),
      prompts: Number(detail.prompt_count || 0),
    })
  }
  return String(detail.server_id || '')
}
</script>

<style scoped>
.mode-switch, .import-panel, .preview-list, .test-row { display: grid; gap: var(--app-space-md); }
.mode-switch { margin-bottom: var(--app-space-lg); }
.preview-card { padding: var(--app-space-md); border: 1px solid var(--app-divider); border-radius: var(--app-radius-md); background: var(--app-surface-soft); }
.preview-heading, .preview-meta { display: flex; align-items: center; justify-content: space-between; gap: var(--app-space-md); }
.preview-command { display: block; margin-top: var(--app-space-xs); font-family: var(--app-font-mono); overflow-wrap: anywhere; }
.preview-meta { margin-top: var(--app-space-sm); color: var(--app-text-muted); font-size: var(--app-font-xs); justify-content: flex-start; flex-wrap: wrap; }
.test-row { gap: var(--app-space-xs); margin-top: var(--app-space-xs); }
.test-heading { display: flex; align-items: center; justify-content: space-between; gap: var(--app-space-md); }
.policy-section { margin-top: 8px; padding: 16px; border: 1px solid var(--app-border); border-radius: 12px; }
.section-copy,.switch-row > span { display: grid; gap: 3px; }
.section-copy { margin-bottom: 12px; }
.section-copy span,.switch-row small { color: var(--app-text-muted); font-size: 10px; }
.switch-row { display: flex; align-items: center; justify-content: space-between; gap: 20px; }
.install-steps { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); margin-bottom: 20px; overflow: hidden; border: 1px solid var(--app-border); border-radius: 13px; }
.install-steps > div { display: flex; min-width: 0; align-items: center; gap: 9px; padding: 11px 12px; border-right: 1px solid var(--app-border); }
.install-steps > div:last-child { border-right: 0; }.install-steps i { display: grid; flex: none; width: 22px; height: 22px; place-items: center; border: 1px solid var(--app-border); border-radius: 50%; font-size: 9px; font-style: normal; }.install-steps span { display: grid; min-width: 0; gap: 1px; }.install-steps strong { font-size: 10px; }.install-steps small { overflow: hidden; color: var(--app-text-muted); font-size: 8px; text-overflow: ellipsis; white-space: nowrap; }.install-steps .active { background: color-mix(in srgb, var(--app-text) 5%, transparent); }.install-steps .active i,.install-steps .done i { color: var(--app-surface); border-color: var(--app-text); background: var(--app-text); }.install-steps .pending { opacity: .48; }
.install-console { display: grid; gap: 13px; margin-top: 18px; padding: 15px; border: 1px solid var(--app-border); border-radius: 13px; background: var(--app-surface); }.install-console header { display: flex; align-items: center; justify-content: space-between; gap: 16px; }.install-console header > div { display: grid; gap: 2px; }.console-kicker { color: var(--app-text-muted); font-size: 8px; font-weight: 800; letter-spacing: .14em; }.install-console header strong { font-size: 12px; }.install-timeline { display: grid; max-height: 230px; overflow-y: auto; }.install-event { position: relative; display: grid; grid-template-columns: 12px minmax(0, 1fr); gap: 9px; min-height: 42px; }.install-event::before { position: absolute; top: 14px; bottom: 0; left: 4px; width: 1px; content: ''; background: var(--app-border); }.install-event:last-child::before { display: none; }.install-event > i { z-index: 1; width: 9px; height: 9px; margin-top: 3px; border: 2px solid var(--app-surface); border-radius: 50%; background: var(--app-text); }.install-event > div { display: grid; align-content: start; gap: 3px; padding-bottom: 11px; }.install-event strong { font-size: 10px; }.install-event span { color: var(--app-text-muted); font-family: var(--app-font-mono); font-size: 9px; overflow-wrap: anywhere; }.install-error { margin: 0; padding: 10px; color: var(--app-error); border: 1px solid color-mix(in srgb, var(--app-error) 30%, transparent); border-radius: 9px; font-family: var(--app-font-mono); font-size: 10px; white-space: pre-wrap; }
@media (max-width: 680px) { .install-steps { grid-template-columns: 1fr 1fr; }.install-steps > div:nth-child(2) { border-right: 0; }.install-steps > div:nth-child(-n + 2) { border-bottom: 1px solid var(--app-border); } }
</style>
