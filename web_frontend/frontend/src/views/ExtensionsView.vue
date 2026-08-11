<template>
  <main class="library-page">
    <header class="library-header">
      <div class="title-block">
        <span class="eyebrow">CAPABILITY LIBRARY</span>
        <h1>{{ activeHeading.title }}</h1>
        <p>{{ activeHeading.description }}</p>
      </div>
      <div class="header-tools">
        <n-input v-model:value="query" clearable placeholder="搜索名称、说明或关键词" class="search-input">
          <template #prefix><n-icon><SearchOutline /></n-icon></template>
        </n-input>
        <n-button quaternary circle :loading="loading" aria-label="刷新能力库" @click="loadAll">
          <template #icon><n-icon><Refresh /></n-icon></template>
        </n-button>
      </div>
    </header>

    <n-alert v-if="loadError" type="error" closable class="page-alert" @close="loadError = ''">{{ loadError }}</n-alert>
    <n-alert v-if="probeResult" type="success" closable class="page-alert" @close="probeResult = null">
      {{ t('capabilityPools.probeSucceeded', { count: probeResult.tool_count }) }} ·
      {{ probeResult.tools.join('、') || t('capabilityPools.noDiscoveredTools') }}
    </n-alert>

    <section class="pool-surface">
      <div class="pool-heading">
        <div>
          <span class="pool-kicker">{{ activeHeading.kicker }}</span>
          <h2>{{ activeHeading.listTitle }}</h2>
          <p>{{ visibleItems.length }} 项已载入，可搜索并打开编辑。</p>
        </div>
        <n-button v-if="activePool === 'mcp'" type="primary" round @click="openAddMcp">
          <template #icon><n-icon><Add /></n-icon></template>
          {{ t('extensions.addServer') }}
        </n-button>
      </div>

      <div v-if="visibleItems.length" class="card-grid">
        <article
          v-for="item in visibleItems"
          :key="itemKey(item)"
          class="pool-card"
          tabindex="0"
          @click="openItem(item)"
          @keydown.enter="openItem(item)"
        >
          <div class="card-header">
            <span class="type-pill">{{ itemType(item) }}</span>
            <span class="status" :class="{ muted: !itemEnabled(item) }">
              <i />{{ itemEnabled(item) ? '可用' : '停用' }}
            </span>
          </div>
          <div class="card-body">
            <h3>{{ itemName(item) }}</h3>
            <p>{{ itemDescription(item) }}</p>
          </div>
          <div class="card-facts">
            <span v-for="fact in itemFacts(item)" :key="fact">{{ fact }}</span>
          </div>
          <footer class="card-footer">
            <span>{{ itemSource(item) }}</span>
            <div class="card-buttons">
              <n-button
                v-if="isMcpServer(item)"
                size="small"
                quaternary
                :loading="probingId === item.capability_id"
                @click.stop="probeMcp(item)"
              >测试</n-button>
              <n-button size="small" quaternary @click.stop="editItem(item)">
                编辑
              </n-button>
            </div>
          </footer>
        </article>
      </div>
      <n-empty v-else class="empty-state" :description="query.trim() ? '没有匹配的结果' : activeHeading.empty" />
    </section>

    <n-drawer v-model:show="showToolEditor" :width="600" placement="right">
      <n-drawer-content title="工具配置" closable>
        <template v-if="editingTool">
          <div class="editor-intro">
            <span class="type-pill">{{ editingTool.kind === 'mcp_tool' ? 'MCP TOOL' : 'TOOL' }}</span>
            <p>这里的设置会进入下一次能力快照，并直接约束运行时执行。</p>
          </div>
          <n-form label-placement="top" class="editor-form">
            <section class="form-section">
              <div class="section-title"><strong>呈现给模型的信息</strong><span>名称用于识别，说明会进入模型上下文。</span></div>
              <n-form-item label="显示名称"><n-input v-model:value="toolForm.display_name" /></n-form-item>
              <n-form-item label="工具说明">
                <n-input v-model:value="toolForm.description" type="textarea" :autosize="{ minRows: 4, maxRows: 9 }" />
              </n-form-item>
            </section>
            <section class="form-section two-column">
              <div class="section-title full"><strong>权限与风险</strong><span>对话的三档权限仍是上层规则，这里定义单个工具的边界。</span></div>
              <n-form-item label="审批策略">
                <n-select v-model:value="toolForm.approval" :options="approvalOptions" />
              </n-form-item>
              <n-form-item label="风险级别">
                <n-select v-model:value="toolForm.risk_level" :options="riskOptions" />
              </n-form-item>
            </section>
            <section class="form-section">
              <div class="section-row">
                <div class="section-title"><strong>并发调用</strong><span>允许同一工具同时处理多个请求。</span></div>
                <n-switch v-model:value="toolForm.allow_parallel_calls" @update:value="normalizeParallel" />
              </div>
              <n-form-item v-if="toolForm.allow_parallel_calls" label="最大并发请求数">
                <n-input-number v-model:value="toolForm.max_parallel_calls" :min="1" :max="128" />
              </n-form-item>
              <n-form-item label="单次调用超时（秒）">
                <n-input-number v-model:value="toolForm.timeout_seconds" :min="1" :max="3600" />
              </n-form-item>
            </section>
            <section class="form-section">
              <div class="section-title"><strong>输出控制</strong><span>限制进入模型上下文的工具结果，原始结果可独立保留。</span></div>
              <n-form-item label="输出处理">
                <n-radio-group v-model:value="toolForm.output_projection">
                  <n-space><n-radio value="compress">超限压缩</n-radio><n-radio value="passthrough">原样传递</n-radio></n-space>
                </n-radio-group>
              </n-form-item>
              <n-form-item v-if="toolForm.output_projection === 'compress'" label="模型可见字符上限">
                <n-input-number v-model:value="toolForm.output_max_model_chars" :min="1000" :max="1000000" :step="1000" />
              </n-form-item>
              <div class="switch-line"><span><strong>保留原始输出</strong><small>压缩前的完整结果仍可通过输出工具读取。</small></span><n-switch v-model:value="toolForm.retain_raw_output" /></div>
            </section>
          </n-form>
        </template>
        <template #footer>
          <n-space justify="end"><n-button @click="showToolEditor = false">取消</n-button><n-button type="primary" :loading="savingTool" @click="saveTool">保存并发布</n-button></n-space>
        </template>
      </n-drawer-content>
    </n-drawer>

    <n-modal v-model:show="showSkillEditor" preset="card" class="skill-editor" :style="{ width: 'min(1040px, calc(100vw - 48px))' }" title="Skill 编辑器" :bordered="false">
      <n-spin :show="loadingSkill">
        <template v-if="skillDocument">
          <div class="skill-editor-header">
            <div><span class="type-pill">SKILL</span><strong>{{ String(skillForm.metadata.display_name || skillForm.metadata.name || '') }}</strong></div>
            <span>{{ skillDocument.source_path }}</span>
          </div>
          <n-tabs v-model:value="skillTab" type="line" animated>
            <n-tab-pane name="metadata" tab="基本信息">
              <div class="skill-pane narrow-pane">
                <n-form label-placement="top">
                  <n-form-item label="标识"><n-input :value="String(skillForm.metadata.name || '')" disabled /></n-form-item>
                  <n-form-item label="显示名称"><n-input v-model:value="skillDisplayName" placeholder="可选；留空时使用标识" /></n-form-item>
                  <n-form-item label="能力说明"><n-input v-model:value="skillDescription" type="textarea" :autosize="{ minRows: 4, maxRows: 8 }" /></n-form-item>
                  <n-form-item label="关键词"><n-dynamic-tags v-model:value="skillKeywords" /></n-form-item>
                </n-form>
              </div>
            </n-tab-pane>
            <n-tab-pane name="instructions" tab="指令正文">
              <div class="skill-pane instruction-pane">
                <div class="pane-note"><strong>SKILL.md</strong><span>使用 Markdown 编写完整执行约束、流程和交付标准。</span></div>
                <n-input v-model:value="skillForm.instructions" type="textarea" class="code-editor" :autosize="{ minRows: 22, maxRows: 34 }" />
              </div>
            </n-tab-pane>
            <n-tab-pane name="resources" :tab="`资源文件 · ${skillDocument.resources.length}`">
              <div class="resource-editor">
                <aside>
                  <button
                    v-for="resource in skillDocument.resources"
                    :key="resource.path"
                    type="button"
                    :class="{ active: selectedResourcePath === resource.path }"
                    @click="selectedResourcePath = resource.path"
                  >
                    <span>{{ resource.path }}</span><small>{{ formatBytes(resource.size_bytes) }}{{ resource.editable ? '' : ' · 只读' }}</small>
                  </button>
                </aside>
                <section v-if="selectedResource" class="resource-content">
                  <div class="pane-note"><strong>{{ selectedResource.path }}</strong><span>{{ selectedResource.editable ? '文本资源，可直接编辑' : '二进制资源，仅展示文件信息' }}</span></div>
                  <n-input v-if="selectedResource.editable" v-model:value="skillResources[selectedResource.path]" type="textarea" class="code-editor" :autosize="{ minRows: 20, maxRows: 32 }" />
                  <n-empty v-else description="该资源不是 UTF-8 文本，不能在此编辑" />
                </section>
                <n-empty v-else class="resource-empty" description="选择一个资源文件" />
              </div>
            </n-tab-pane>
          </n-tabs>
        </template>
      </n-spin>
      <template #footer><n-space justify="end"><n-button @click="showSkillEditor = false">取消</n-button><n-button type="primary" :loading="savingSkill" :disabled="!skillDocument" @click="saveSkillContent">保存并发布</n-button></n-space></template>
    </n-modal>

    <McpConfigModal v-model:show="showMcpModal" :item="editingMcpItem" :edit-config="editingMcpConfig" :busy="savingMcp" @submit="saveMcpServers" />
  </main>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import {
  NAlert, NButton, NDrawer, NDrawerContent, NDynamicTags, NEmpty, NForm, NFormItem, NIcon,
  NInput, NInputNumber, NModal, NRadio, NRadioGroup, NSelect, NSpace, NSpin, NSwitch,
  NTabPane, NTabs, useMessage,
} from 'naive-ui'
import { Add, Refresh, SearchOutline } from '@/components/icons'
import McpConfigModal from '@/components/extensions/McpConfigModal.vue'
import {
  capabilityPoolsApi,
  type CapabilityPoolItem,
  type CapabilityPoolSnapshot,
  type McpProbeResult,
  type SkillEditorDocument,
  type SkillEditorResource,
  type ToolRuntimePolicyInput,
} from '@/api/capabilityPools'
import type { McpServerConfig } from '@/api/resourceTypes'
import type { ExtensionItemView } from '@/types/protocol'
import { useI18n } from '@/composables/useI18n'

type PoolName = 'mcp' | 'tools' | 'skills'
type PoolItem = CapabilityPoolItem
const props = defineProps<{ pool: PoolName }>()
const { t } = useI18n()
const message = useMessage()
const snapshot = ref<CapabilityPoolSnapshot | null>(null)
const loading = ref(false)
const loadError = ref('')
const query = ref('')
const activePool = computed(() => props.pool)
const probingId = ref('')
const probeResult = ref<McpProbeResult | null>(null)
const showMcpModal = ref(false)
const savingMcp = ref(false)
const editingMcp = ref<CapabilityPoolItem | null>(null)
const showToolEditor = ref(false)
const savingTool = ref(false)
const editingTool = ref<CapabilityPoolItem | null>(null)
const showSkillEditor = ref(false)
const loadingSkill = ref(false)
const savingSkill = ref(false)
const skillDocument = ref<SkillEditorDocument | null>(null)
const skillTab = ref('metadata')
const selectedResourcePath = ref('')
const skillResources = reactive<Record<string, string>>({})
const skillForm = reactive<{ metadata: Record<string, unknown>; instructions: string }>({ metadata: {}, instructions: '' })
const toolForm = reactive<ToolRuntimePolicyInput & { display_name: string; description: string }>({
  display_name: '', description: '', approval: 'inherit', risk_level: 'low', allow_parallel_calls: true,
  max_parallel_calls: 1, timeout_seconds: 300, output_projection: 'compress', output_max_model_chars: 50000,
  retain_raw_output: true,
})

const mcpServers = computed(() => capabilitiesOf('mcp_server'))
const tools = computed(() => (snapshot.value?.capabilities || []).filter(item => item.kind === 'tool' || item.kind === 'mcp_tool'))
const skills = computed(() => capabilitiesOf('skill'))
const filteredMcp = computed(() => filterCapabilities(mcpServers.value))
const filteredTools = computed(() => filterCapabilities(tools.value))
const filteredSkills = computed(() => filterCapabilities(skills.value))
const visibleItems = computed<PoolItem[]>(() => ({ mcp: filteredMcp.value, tools: filteredTools.value, skills: filteredSkills.value })[activePool.value])
const headings: Record<PoolName, { kicker: string; title: string; listTitle: string; description: string; empty: string }> = {
  mcp: { kicker: 'CONNECTIONS', title: 'MCP 池', listTitle: '已注册服务', description: '管理服务连接、凭据引用、超时、并发与发现到的工具。', empty: '暂无 MCP 服务' },
  tools: { kicker: 'EXECUTION', title: '工具池', listTitle: '运行时工具', description: '统一管理内置工具与 MCP 工具的说明、权限、输出和并发策略。', empty: '暂无可用工具' },
  skills: { kicker: 'INSTRUCTIONS', title: 'Skill 池', listTitle: '已解析 Skill', description: '编辑 Skill 元信息、完整指令正文以及随附资源文件。', empty: '暂无 Skill' },
}
const activeHeading = computed(() => headings[activePool.value])
const editingMcpConfig = computed(() => editingMcp.value?.details.registry_config as Record<string, unknown> | undefined || null)
const editingMcpItem = computed<ExtensionItemView | null>(() => editingMcp.value ? ({ name: editingMcp.value.display_name, kind: 'mcp', enabled: true, payload: { ...(editingMcpConfig.value || {}), server_id: serverId(editingMcp.value), display_name: editingMcp.value.display_name, description: editingMcp.value.description } }) : null)
const selectedResource = computed<SkillEditorResource | null>(() => skillDocument.value?.resources.find(item => item.path === selectedResourcePath.value) || null)
const approvalOptions = [
  { label: '跟随对话权限', value: 'inherit' }, { label: '自动放行', value: 'allow' },
  { label: '每次确认', value: 'ask' }, { label: '禁止调用', value: 'deny' },
]
const riskOptions = [{ label: '低风险', value: 'low' }, { label: '中风险', value: 'medium' }, { label: '高风险', value: 'high' }]
const skillDisplayName = computed({ get: () => String(skillForm.metadata.display_name || ''), set: value => { if (value.trim()) skillForm.metadata.display_name = value; else delete skillForm.metadata.display_name } })
const skillDescription = computed({ get: () => String(skillForm.metadata.description || ''), set: value => { skillForm.metadata.description = value } })
const skillKeywords = computed<string[]>({
  get: () => { const value = skillForm.metadata.keywords || skillForm.metadata.tags || []; return Array.isArray(value) ? value.map(String) : [] },
  set: value => { skillForm.metadata.keywords = value; delete skillForm.metadata.tags },
})

function capabilitiesOf(kind: CapabilityPoolItem['kind']) { return (snapshot.value?.capabilities || []).filter(item => item.kind === kind) }
function matches(values: unknown[]) { const needle = query.value.trim().toLocaleLowerCase(); return !needle || values.some(value => String(value || '').toLocaleLowerCase().includes(needle)) }
function filterCapabilities(items: CapabilityPoolItem[]) { return items.filter(item => matches([item.display_name, item.description, item.namespace, ...item.keywords, capabilityName(item)])) }
function isMcpServer(item: PoolItem): item is CapabilityPoolItem { return item.kind === 'mcp_server' }
function itemKey(item: PoolItem) { return item.capability_id }
function itemName(item: PoolItem) { return capabilityName(item) }
function itemDescription(item: PoolItem) { return item.description || t('common.noDescription') }
function itemEnabled(item: PoolItem) { return item.health === 'healthy' || item.health === null }
function itemType(item: PoolItem) { return ({ mcp_server: 'MCP', mcp_tool: 'MCP TOOL', tool: 'TOOL', skill: 'SKILL' } as const)[item.kind] }
function itemSource(item: PoolItem) { if (item.kind === 'mcp_tool') return '来自 MCP'; if (item.kind === 'tool') return '内置运行时'; if (item.kind === 'skill') return item.trust_level === 'local_user' ? '本地 Skill' : item.trust_level; return transportLabel(item) }
function itemFacts(item: PoolItem) {
  if (item.kind === 'mcp_server') return [`${mcpToolCount(item.capability_id)} 个工具`, `${item.details.max_parallel_requests || 1} 并发`]
  if (item.kind === 'skill') return [`${item.details.content_count || 1} 个文件`, formatBytes(Number(item.details.total_size_bytes || 0))]
  return [riskLabel(item.details.risk_level), item.details.allow_parallel_calls ? `${item.details.max_parallel_calls || 1} 并发` : '串行', outputLabel(item)]
}
function capabilityName(item: CapabilityPoolItem) { return item.kind === 'mcp_tool' ? String(item.details.upstream_tool_name || item.display_name) : item.display_name }
function serverId(item: CapabilityPoolItem) { return item.capability_id.replace(/^mcp-server:\/\//, '') }
function mcpToolCount(id: string) { return tools.value.filter(item => item.kind === 'mcp_tool' && item.details.server_capability_id === id).length }
function transportLabel(item: CapabilityPoolItem) { return ({ stdio: '本地进程', streamable_http: 'Streamable HTTP', sse: 'SSE' } as Record<string, string>)[String(item.details.transport)] || 'MCP' }
function riskLabel(value: unknown) { return ({ low: '低风险', medium: '中风险', high: '高风险' } as Record<string, string>)[String(value)] || '风险未标注' }
function outputLabel(item: CapabilityPoolItem) { return item.details.output_projection === 'passthrough' ? '原样输出' : `压缩至 ${Number(item.details.output_max_model_chars || 50000).toLocaleString()} 字符` }
function formatBytes(value: number) { if (value < 1024) return `${value} B`; if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`; return `${(value / 1024 / 1024).toFixed(1)} MB` }

async function loadAll() { loading.value = true; loadError.value = ''; try { snapshot.value = await capabilityPoolsApi.snapshot() } catch (error) { loadError.value = error instanceof Error ? error.message : String(error) } finally { loading.value = false } }
async function probeMcp(item: CapabilityPoolItem) { probingId.value = item.capability_id; probeResult.value = null; try { probeResult.value = await capabilityPoolsApi.probeMcp(item.capability_id) } catch (error) { message.error(error instanceof Error ? error.message : String(error)) } finally { probingId.value = '' } }
function openAddMcp() { editingMcp.value = null; showMcpModal.value = true }
function openItem(item: PoolItem) { editItem(item) }
function editItem(item: PoolItem) { if (item.kind === 'mcp_server') { editingMcp.value = item; showMcpModal.value = true; return } if (item.kind === 'skill') { void openSkillEditor(item); return } openToolEditor(item) }
function openToolEditor(item: CapabilityPoolItem) { editingTool.value = item; Object.assign(toolForm, { display_name: item.display_name, description: item.description, approval: item.details.approval || 'inherit', risk_level: item.details.risk_level || 'low', allow_parallel_calls: item.details.allow_parallel_calls !== false, max_parallel_calls: Number(item.details.max_parallel_calls || 1), timeout_seconds: Number(item.details.timeout_seconds || 300), output_projection: item.details.output_projection || 'compress', output_max_model_chars: Number(item.details.output_max_model_chars || 50000), retain_raw_output: item.details.retain_raw_output !== false }); showToolEditor.value = true }
function normalizeParallel(value: boolean) { if (!value) toolForm.max_parallel_calls = 1 }
async function saveTool() { if (!editingTool.value) return; savingTool.value = true; try { snapshot.value = await capabilityPoolsApi.updateTool(editingTool.value, { display_name: toolForm.display_name.trim(), description: toolForm.description.trim(), runtime_policy: { approval: toolForm.approval, risk_level: toolForm.risk_level, allow_parallel_calls: toolForm.allow_parallel_calls, max_parallel_calls: toolForm.allow_parallel_calls ? toolForm.max_parallel_calls : 1, timeout_seconds: toolForm.timeout_seconds, output_projection: toolForm.output_projection, output_max_model_chars: toolForm.output_max_model_chars, retain_raw_output: toolForm.retain_raw_output } }); showToolEditor.value = false; message.success('工具配置已发布') } catch (error) { message.error(error instanceof Error ? error.message : String(error)) } finally { savingTool.value = false } }
async function openSkillEditor(item: CapabilityPoolItem) { showSkillEditor.value = true; loadingSkill.value = true; skillDocument.value = null; skillTab.value = 'metadata'; try { const document = await capabilityPoolsApi.skillEditor(item.capability_id); skillDocument.value = document; skillForm.metadata = structuredClone(document.metadata); skillForm.instructions = document.instructions; for (const key of Object.keys(skillResources)) delete skillResources[key]; document.resources.filter(resource => resource.editable).forEach(resource => { skillResources[resource.path] = resource.content || '' }); selectedResourcePath.value = document.resources[0]?.path || '' } catch (error) { showSkillEditor.value = false; message.error(error instanceof Error ? error.message : String(error)) } finally { loadingSkill.value = false } }
async function saveSkillContent() { if (!skillDocument.value) return; savingSkill.value = true; try { snapshot.value = await capabilityPoolsApi.updateSkillContent(skillDocument.value, { metadata: skillForm.metadata, instructions: skillForm.instructions, resources: { ...skillResources } }); showSkillEditor.value = false; message.success('Skill 已校验并发布') } catch (error) { message.error(error instanceof Error ? error.message : String(error)) } finally { savingSkill.value = false } }
async function saveMcpServers(servers: McpServerConfig[]) { if (!snapshot.value) return; savingMcp.value = true; try { let current = snapshot.value; if (editingMcp.value) { if (servers.length !== 1) throw new Error('编辑 MCP 时只能提交一个服务'); current = await capabilityPoolsApi.updateMcp(serverId(editingMcp.value), servers[0], current.mcp_registry_digest) } else { for (const server of servers) current = await capabilityPoolsApi.addMcp(server, current.mcp_registry_digest) } snapshot.value = current; showMcpModal.value = false; editingMcp.value = null; message.success('MCP 已保存') } catch (error) { message.error(error instanceof Error ? error.message : String(error)) } finally { savingMcp.value = false } }

onMounted(loadAll)
</script>

<style scoped>
.library-page { min-height: 100%; padding: clamp(28px, 4vw, 52px); color: var(--app-text); background: var(--app-background); }
.library-header { display: flex; align-items: flex-end; justify-content: space-between; gap: 32px; max-width: 1540px; margin: 0 auto 28px; }
.title-block { max-width: 760px; }.eyebrow,.pool-kicker { display: block; margin-bottom: 9px; color: var(--app-text-muted); font-size: 10px; font-weight: 800; letter-spacing: .16em; }.title-block h1 { margin: 0; font-size: clamp(32px, 4vw, 48px); line-height: 1; letter-spacing: -.045em; }.title-block p,.pool-heading p { margin: 13px 0 0; color: var(--app-text-secondary); font-size: 13px; line-height: 1.6; }.header-tools { display: flex; align-items: center; gap: 8px; }.search-input { width: min(360px, 34vw); }
.pool-switcher { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; max-width: 1540px; margin: 0 auto 16px; }.pool-switch { display: grid; grid-template-columns: 1fr auto; gap: 5px 14px; min-width: 0; padding: 16px 18px; color: inherit; text-align: left; border: 1px solid var(--app-border); border-radius: 14px; background: var(--app-surface); cursor: pointer; transition: border-color .16s ease, box-shadow .16s ease, transform .16s ease; }.pool-switch:hover { transform: translateY(-1px); border-color: var(--app-border-focus); }.pool-switch.active { border-color: color-mix(in srgb, var(--app-text) 38%, var(--app-border)); box-shadow: inset 0 -2px 0 var(--app-text); }.switch-label { font-size: 12px; font-weight: 750; }.pool-switch strong { grid-row: span 2; align-self: center; font-size: 26px; letter-spacing: -.04em; }.pool-switch small { overflow: hidden; color: var(--app-text-muted); text-overflow: ellipsis; white-space: nowrap; }
.page-alert { max-width: 1540px; margin: 12px auto; }.pool-surface { max-width: 1540px; margin: 0 auto; padding: 24px; border: 1px solid var(--app-border); border-radius: 20px; background: var(--app-surface); }.pool-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; padding: 2px 2px 22px; border-bottom: 1px solid var(--app-border); }.pool-heading h2 { margin: 0; font-size: 22px; letter-spacing: -.02em; }
.card-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; padding-top: 18px; }.pool-card { display: flex; min-height: 214px; flex-direction: column; padding: 17px 18px 14px; border: 1px solid var(--app-border); border-radius: 15px; background: var(--app-surface); cursor: pointer; transition: border-color .16s ease, box-shadow .16s ease, transform .16s ease; }.pool-card:hover,.pool-card:focus-visible { transform: translateY(-2px); border-color: var(--app-border-focus); box-shadow: 0 12px 28px color-mix(in srgb, var(--app-text) 7%, transparent); outline: none; }.card-header,.card-footer,.status,.card-buttons,.skill-editor-header,.skill-editor-header > div,.section-row,.switch-line { display: flex; align-items: center; }.card-header,.card-footer,.section-row,.switch-line { justify-content: space-between; }.type-pill { display: inline-flex; width: fit-content; padding: 4px 7px; border-radius: 6px; background: var(--app-text); color: var(--app-surface); font-size: 9px; font-weight: 800; letter-spacing: .08em; }.status { gap: 6px; color: var(--app-text-muted); font-size: 10px; }.status i { width: 6px; height: 6px; border-radius: 50%; background: var(--app-success, #2ca66f); }.status.muted i { background: var(--app-text-muted); }.card-body { flex: 1; padding: 22px 0 14px; }.card-body h3 { margin: 0; overflow: hidden; font-size: 16px; letter-spacing: -.01em; text-overflow: ellipsis; white-space: nowrap; }.card-body p { display: -webkit-box; margin: 8px 0 0; overflow: hidden; color: var(--app-text-secondary); font-size: 12px; line-height: 1.6; -webkit-box-orient: vertical; -webkit-line-clamp: 3; }.card-facts { display: flex; min-height: 24px; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; }.card-facts span { padding: 3px 7px; border-radius: 6px; background: var(--app-surface-subtle, color-mix(in srgb, var(--app-text) 5%, transparent)); color: var(--app-text-muted); font-size: 9px; }.card-footer { min-height: 30px; padding-top: 11px; border-top: 1px solid var(--app-border); color: var(--app-text-muted); font-size: 10px; }.card-buttons { gap: 1px; }.empty-state { padding: 90px 0; }
.editor-intro { padding: 2px 0 22px; border-bottom: 1px solid var(--app-border); }.editor-intro p { margin: 12px 0 0; color: var(--app-text-secondary); font-size: 12px; }.editor-form { display: grid; gap: 14px; padding-top: 18px; }.form-section { padding: 17px; border: 1px solid var(--app-border); border-radius: 13px; }.form-section.two-column { display: grid; grid-template-columns: 1fr 1fr; gap: 0 14px; }.section-title { display: grid; gap: 3px; margin-bottom: 15px; }.section-title.full { grid-column: 1 / -1; }.section-title strong,.switch-line strong { font-size: 13px; }.section-title span,.switch-line small { color: var(--app-text-muted); font-size: 10px; line-height: 1.5; }.section-row .section-title { margin-bottom: 10px; }.switch-line > span { display: grid; gap: 3px; }
.skill-editor :deep(.n-card__content) { padding-top: 4px; }.skill-editor-header { justify-content: space-between; gap: 20px; min-width: 0; padding: 0 0 16px; border-bottom: 1px solid var(--app-border); }.skill-editor-header > div { gap: 10px; }.skill-editor-header > span { overflow: hidden; color: var(--app-text-muted); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }.skill-pane { padding-top: 18px; }.narrow-pane { width: min(650px, 100%); }.pane-note { display: grid; gap: 3px; margin-bottom: 10px; }.pane-note span { color: var(--app-text-muted); font-size: 10px; }.code-editor :deep(textarea) { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 12px; line-height: 1.65; }.resource-editor { display: grid; grid-template-columns: 260px minmax(0, 1fr); min-height: 470px; margin-top: 18px; overflow: hidden; border: 1px solid var(--app-border); border-radius: 12px; }.resource-editor aside { padding: 8px; overflow-y: auto; border-right: 1px solid var(--app-border); background: var(--app-surface-subtle, color-mix(in srgb, var(--app-text) 3%, transparent)); }.resource-editor aside button { display: grid; width: 100%; gap: 3px; padding: 10px; color: inherit; text-align: left; border: 0; border-radius: 8px; background: transparent; cursor: pointer; }.resource-editor aside button:hover,.resource-editor aside button.active { background: var(--app-surface); }.resource-editor aside span { overflow: hidden; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }.resource-editor aside small { color: var(--app-text-muted); font-size: 9px; }.resource-content { min-width: 0; padding: 15px; }.resource-empty { align-self: center; }
@media (max-width: 920px) { .library-header { align-items: flex-start; flex-direction: column; }.header-tools,.search-input { width: 100%; }.pool-switcher { grid-template-columns: repeat(2, 1fr); }.resource-editor { grid-template-columns: 210px minmax(0, 1fr); } }
@media (max-width: 620px) { .library-page { padding: 20px 14px; }.pool-switcher { grid-template-columns: 1fr 1fr; }.pool-switch { padding: 13px; }.pool-switch small { display: none; }.pool-surface { padding: 15px; }.pool-heading { align-items: flex-start; flex-direction: column; }.card-grid { grid-template-columns: 1fr; }.resource-editor { grid-template-columns: 1fr; }.resource-editor aside { max-height: 160px; border-right: 0; border-bottom: 1px solid var(--app-border); }.form-section.two-column { grid-template-columns: 1fr; } }
</style>
