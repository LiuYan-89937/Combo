<template>
  <div class="extension-workbench">
    <header class="workbench-header">
      <div>
        <div class="eyebrow">EXTENSION REGISTRY</div>
        <h1>{{ t('extensions.title') }}</h1>
        <p>统一注册扩展，然后拖动到右侧 Agent 轮盘完成装配。</p>
      </div>
      <n-button quaternary circle class="refresh-button" @click="refreshExtensionWorkbench">
        <template #icon><n-icon><Refresh /></n-icon></template>
      </n-button>
    </header>

    <n-alert
      v-if="extensionStore.testResult && !showMcpModal"
      class="test-result"
      :type="testResultType"
      :title="testResultTitle"
      closable
      @close="extensionStore.setTestResult(null)"
    >
      <McpTestResultDetails :result="extensionStore.testResult" />
    </n-alert>

    <main class="workbench-grid">
      <section class="registry-panel">
        <div class="panel-glow" />
        <n-tabs type="segment" animated class="registry-tabs">
          <n-tab-pane name="mcp" :tab="`MCP · ${extensionStore.mcpItems.length}`">
            <div class="registry-toolbar">
              <div>
                <strong>全局 MCP 注册</strong>
                <span>配置只保存一次，可装配给任意 Agent</span>
              </div>
              <n-button type="primary" @click="openAddMcp">
                <template #icon><n-icon><Add /></n-icon></template>
                {{ t('extensions.addServer') }}
              </n-button>
            </div>

            <div v-if="extensionStore.mcpItems.length" class="registry-cards">
              <article
                v-for="item in extensionStore.mcpItems"
                :key="extensionKey(item)"
                class="registry-card mcp-card"
                draggable="true"
                @dragstart="startExtensionDrag('mcp', String(item.payload?.server_id || ''))"
                @dragend="finishExtensionDrag"
              >
                <div class="drag-grip">⋮⋮</div>
                <div class="card-icon">M</div>
                <div class="card-body">
                  <div class="card-title-row">
                    <strong>{{ item.name }}</strong>
                    <span class="live-dot" />
                  </div>
                  <p>{{ item.payload?.description || item.summary || t('common.noDescription') }}</p>
                  <code>{{ mcpCommandLine(item) }}</code>
                </div>
                <div class="card-actions">
                  <n-button size="tiny" quaternary @click="handleTestMcp(item)">测试</n-button>
                  <n-dropdown :options="mcpActions" @select="(key) => handleMcpAction(key, item)">
                    <n-button size="tiny" quaternary circle>
                      <n-icon><EllipsisHorizontal /></n-icon>
                    </n-button>
                  </n-dropdown>
                </div>
              </article>
            </div>
            <n-empty v-else class="registry-empty" :description="t('extensions.noMcpServers')" />
          </n-tab-pane>

          <n-tab-pane name="skills" :tab="`Skill · ${extensionStore.skillItems.length}`">
            <section class="skillhub-strip">
              <div>
                <strong>{{ t('extensions.skillHubTitle') }}</strong>
                <span>{{ skillHubStatusMessage }}</span>
              </div>
              <n-input
                v-model:value="skillHubQuery"
                size="small"
                :placeholder="t('extensions.skillHubSearchPlaceholder')"
                :disabled="!skillHubCliAvailable"
                @keyup.enter="handleSkillHubSearch"
              />
              <n-button
                size="small"
                type="primary"
                :disabled="!skillHubCliAvailable || !skillHubQuery.trim()"
                @click="handleSkillHubSearch"
              >
                {{ t('extensions.searchSkillHub') }}
              </n-button>
            </section>

            <div v-if="skillHubItems.length" class="skillhub-results">
              <div v-for="item in skillHubItems" :key="item.install_name || item.name">
                <span>{{ item.name }}</span>
                <n-button size="tiny" @click="handleSkillHubInstall(item)">
                  {{ t('extensions.installSkill') }}
                </n-button>
              </div>
            </div>

            <div class="registry-toolbar">
              <div>
                <strong>全局 Skill 注册</strong>
                <span>Skill 内容集中管理，Agent 仅保存绑定</span>
              </div>
              <n-button type="primary" @click="openAddSkill">
                <template #icon><n-icon><Add /></n-icon></template>
                {{ t('extensions.addSkill') }}
              </n-button>
            </div>

            <div v-if="extensionStore.skillItems.length" class="registry-cards">
              <article
                v-for="item in extensionStore.skillItems"
                :key="extensionKey(item)"
                class="registry-card skill-card"
                draggable="true"
                @dragstart="startExtensionDrag('skill', String(item.payload?.skill_id || ''))"
                @dragend="finishExtensionDrag"
              >
                <div class="drag-grip">⋮⋮</div>
                <div class="card-icon">S</div>
                <div class="card-body">
                  <div class="card-title-row"><strong>{{ item.name }}</strong></div>
                  <p>{{ item.payload?.description || item.summary || t('common.noDescription') }}</p>
                  <code>{{ item.payload?.path || t('extensions.pathUnset') }}</code>
                </div>
                <n-dropdown :options="skillActions" @select="(key) => handleSkillAction(key, item)">
                  <n-button size="tiny" quaternary circle>
                    <n-icon><EllipsisHorizontal /></n-icon>
                  </n-button>
                </n-dropdown>
              </article>
            </div>
            <n-empty v-else class="registry-empty" :description="t('extensions.noSkills')" />
          </n-tab-pane>
        </n-tabs>
      </section>

      <section class="assembly-panel" :class="{ 'is-dragging': draggingExtension }">
        <div class="assembly-heading">
          <div>
            <div class="eyebrow">AGENT ASSEMBLY</div>
            <h2>Agent 扩展轮盘</h2>
          </div>
          <span v-if="draggingExtension" class="drop-hint">拖到目标 Agent</span>
        </div>

        <div
          class="agent-orbit"
          :class="{ 'is-dense': assemblyTargets.length > 8 }"
        >
          <div class="orbit-line orbit-line-a" />
          <div class="orbit-line orbit-line-b" />
          <div class="orbit-core">
            <span>当前目标</span>
            <strong>{{ selectedAssemblyTarget?.name || 'Agent' }}</strong>
            <small>{{ targetExtensionCount(selectedAssemblyTarget?.id || '') }} 个扩展</small>
          </div>

          <n-popover
            v-for="(target, index) in assemblyTargets"
            :key="target.id"
            trigger="hover"
            placement="left"
            :show-arrow="false"
            class="agent-extension-popover"
          >
            <template #trigger>
              <button
                class="agent-node"
                :class="{
                  active: selectedAssemblyTargetId === target.id,
                  busy: assemblyBusyTargetId === target.id,
                }"
                :style="wheelNodeStyle(index, assemblyTargets.length)"
                @click="selectedAssemblyTargetId = target.id"
                @dragover.prevent
                @drop.prevent="dropExtensionOnTarget(target.id)"
              >
                <span class="agent-avatar">{{ target.glyph }}</span>
                <span class="agent-name">{{ target.name }}</span>
                <span class="agent-count">{{ targetExtensionCount(target.id) }}</span>
              </button>
            </template>
            <div class="bound-popover">
              <div class="bound-title">
                <strong>{{ target.name }}</strong>
                <span>已装配扩展</span>
              </div>
              <div v-if="targetExtensions(target.id).length" class="bound-list">
                <div v-for="item in targetExtensions(target.id)" :key="extensionKey(item)">
                  <span class="bound-kind">{{ item.kind === 'mcp' ? 'M' : 'S' }}</span>
                  <span>{{ item.name }}</span>
                  <n-button
                    size="tiny"
                    quaternary
                    type="error"
                    @click="removeExtensionFromTarget(
                      target.id,
                      item.kind === 'mcp' ? 'mcp' : 'skill',
                      String(item.payload?.server_id || item.payload?.skill_id || ''),
                    )"
                  >
                    移除
                  </n-button>
                </div>
              </div>
              <n-empty v-else size="small" description="尚未装配扩展" />
            </div>
          </n-popover>
        </div>

        <footer class="assembly-footer">
          <span class="pulse-ring" />
          拖拽后立即保存；进行中的任务保持不变，下一次运行使用最新装配。
        </footer>
      </section>
    </main>

    <McpConfigModal
      v-model:show="showMcpModal"
      :item="editingMcp"
      :edit-config="editingMcpConfig"
      :edit-config-loading="editingMcpConfigLoading"
      :busy="busyKey === 'mcp:install'"
      :stopping="mcpInstallStopping"
      :install-result="mcpInstallDisplayResult"
      @submit="handleInstallMcp"
      @cancel-install="handleStopMcpInstall"
    />
    <SkillConfigModal
      v-model:show="showSkillModal"
      :item="editingSkill"
      @submit="handleSaveSkill"
    />
  </div>
</template>

<script setup lang="ts">
import type { CSSProperties } from 'vue'
import {
  NAlert,
  NButton,
  NDropdown,
  NEmpty,
  NIcon,
  NInput,
  NPopover,
  NTabPane,
  NTabs,
} from 'naive-ui'
import { Add, EllipsisHorizontal, Refresh } from '@/components/icons'
import { useExtensionsManager } from '@/composables/extensions/useExtensionsManager'
import McpConfigModal from '@/components/extensions/McpConfigModal.vue'
import McpTestResultDetails from '@/components/extensions/McpTestResultDetails.vue'
import SkillConfigModal from '@/components/extensions/SkillConfigModal.vue'
import { useI18n } from '@/composables/useI18n'

const { t } = useI18n()
const {
  assemblyBusyTargetId,
  assemblyTargets,
  busyKey,
  draggingExtension,
  dropExtensionOnTarget,
  editingMcp,
  editingMcpConfig,
  editingMcpConfigLoading,
  editingSkill,
  extensionKey,
  extensionStore,
  finishExtensionDrag,
  handleInstallMcp,
  handleMcpAction,
  handleSaveSkill,
  handleSkillAction,
  handleSkillHubInstall,
  handleSkillHubSearch,
  handleStopMcpInstall,
  handleTestMcp,
  mcpActions,
  mcpCommandLine,
  mcpInstallDisplayResult,
  mcpInstallStopping,
  openAddMcp,
  openAddSkill,
  refreshExtensionWorkbench,
  removeExtensionFromTarget,
  selectedAssemblyTarget,
  selectedAssemblyTargetId,
  showMcpModal,
  showSkillModal,
  skillActions,
  skillHubCliAvailable,
  skillHubItems,
  skillHubQuery,
  skillHubStatusMessage,
  startExtensionDrag,
  targetExtensionCount,
  targetExtensions,
  testResultTitle,
  testResultType,
} = useExtensionsManager()

function wheelNodeStyle(index: number, total: number): CSSProperties {
  const usesTwoRings = total > 8
  const ring = usesTwoRings ? index % 2 : 0
  const ringIndex = usesTwoRings ? Math.floor(index / 2) : index
  const ringCount = usesTwoRings
    ? Math.ceil((total - ring) / 2)
    : total
  const angle = ringCount <= 1 ? -90 : -90 + (360 / ringCount) * ringIndex
  return {
    '--orbit-angle': `${angle}deg`,
    '--orbit-delay': `${index * -0.45}s`,
    '--orbit-radius': usesTwoRings
      ? (ring === 0 ? 'clamp(164px, 15vw, 196px)' : 'clamp(112px, 10.5vw, 140px)')
      : 'clamp(164px, 15vw, 205px)',
  } as CSSProperties
}
</script>

<style scoped>
.extension-workbench {
  position: relative;
  height: 100%;
  overflow: auto;
  padding: 28px 30px 34px;
  color: var(--app-text);
  background:
    radial-gradient(circle at 82% 48%, rgba(111, 89, 255, .12), transparent 34%),
    radial-gradient(circle at 16% 8%, rgba(51, 185, 255, .09), transparent 28%),
    linear-gradient(145deg, var(--app-surface) 0%, color-mix(in srgb, var(--app-surface) 94%, #6f59ff) 100%);
}

.extension-workbench::before {
  content: "";
  position: fixed;
  inset: 0;
  pointer-events: none;
  opacity: .22;
  background-image: radial-gradient(circle, currentColor .55px, transparent .7px);
  background-size: 24px 24px;
  mask-image: linear-gradient(to bottom, black, transparent 78%);
}

.workbench-header {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 24px;
}

.eyebrow {
  color: #7967ff;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: .18em;
}

h1, h2 { margin: 5px 0 0; letter-spacing: -.035em; }
h1 { font-size: 28px; }
h2 { font-size: 20px; }
.workbench-header p { margin: 7px 0 0; color: var(--app-text-muted); }

.refresh-button {
  border: 1px solid color-mix(in srgb, var(--app-border) 70%, transparent);
  backdrop-filter: blur(18px);
}

.test-result { margin-bottom: 18px; }

.workbench-grid {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: minmax(410px, .92fr) minmax(520px, 1.08fr);
  gap: 20px;
  min-height: 650px;
}

.registry-panel, .assembly-panel {
  position: relative;
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--app-border) 72%, transparent);
  border-radius: 28px;
  background: color-mix(in srgb, var(--app-surface) 84%, transparent);
  box-shadow: 0 24px 70px rgba(27, 24, 58, .08);
  backdrop-filter: blur(24px) saturate(135%);
}

.registry-panel { padding: 18px; }
.panel-glow {
  position: absolute;
  width: 260px;
  height: 260px;
  left: -100px;
  top: -130px;
  border-radius: 50%;
  background: rgba(71, 183, 255, .14);
  filter: blur(55px);
}

.registry-tabs { position: relative; z-index: 1; }
.registry-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  padding: 17px 4px 14px;
}
.registry-toolbar > div { display: grid; gap: 3px; }
.registry-toolbar span, .skillhub-strip span { color: var(--app-text-muted); font-size: 12px; }

.registry-cards { display: grid; gap: 10px; }
.registry-card {
  display: grid;
  grid-template-columns: 18px 42px minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
  min-height: 88px;
  padding: 13px 12px;
  border: 1px solid color-mix(in srgb, var(--app-border) 68%, transparent);
  border-radius: 18px;
  cursor: grab;
  background: color-mix(in srgb, var(--app-surface) 91%, transparent);
  transition: transform .24s ease, box-shadow .24s ease, border-color .24s ease;
}
.registry-card:hover {
  transform: translateY(-3px) scale(1.008);
  border-color: rgba(112, 91, 255, .45);
  box-shadow: 0 15px 36px rgba(59, 48, 133, .11);
}
.registry-card:active { cursor: grabbing; }
.drag-grip { color: var(--app-text-muted); opacity: .5; letter-spacing: -4px; }
.card-icon, .bound-kind {
  display: grid;
  place-items: center;
  border-radius: 13px;
  font-weight: 800;
}
.card-icon { width: 42px; height: 42px; }
.mcp-card .card-icon { color: #196bb0; background: rgba(70, 173, 255, .14); }
.skill-card .card-icon { color: #6a4bd6; background: rgba(126, 92, 255, .13); }
.card-body { min-width: 0; }
.card-title-row { display: flex; align-items: center; gap: 8px; }
.card-body p {
  overflow: hidden;
  margin: 5px 0;
  color: var(--app-text-muted);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.card-body code {
  display: block;
  overflow: hidden;
  color: color-mix(in srgb, var(--app-text) 72%, #765fff);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.card-actions { display: flex; align-items: center; }
.live-dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: #36d391;
  box-shadow: 0 0 0 5px rgba(54, 211, 145, .1);
}
.registry-empty { padding: 70px 0; }

.skillhub-strip {
  display: grid;
  grid-template-columns: minmax(145px, .8fr) minmax(160px, 1fr) auto;
  align-items: center;
  gap: 10px;
  margin: 14px 3px 4px;
  padding: 13px;
  border-radius: 16px;
  background: rgba(121, 103, 255, .07);
}
.skillhub-strip > div { display: grid; }
.skillhub-results { display: grid; gap: 6px; padding: 8px 3px; }
.skillhub-results > div {
  display: flex; justify-content: space-between; align-items: center;
  padding: 8px 10px; border-radius: 10px; background: var(--app-surface-soft);
}

.assembly-panel {
  min-height: 650px;
  padding: 24px;
  transition: border-color .25s ease, box-shadow .25s ease;
}
.assembly-panel.is-dragging {
  border-color: rgba(117, 94, 255, .6);
  box-shadow: 0 26px 90px rgba(86, 62, 205, .17);
}
.assembly-heading { display: flex; justify-content: space-between; align-items: center; }
.drop-hint {
  padding: 7px 11px;
  border-radius: 999px;
  color: #684ff0;
  background: rgba(117, 94, 255, .1);
  animation: hintPulse 1.2s ease-in-out infinite;
}

.agent-orbit {
  position: absolute;
  inset: 82px 12px 52px;
  min-height: 490px;
}
.orbit-line {
  position: absolute;
  left: 50%; top: 50%;
  border: 1px solid rgba(117, 94, 255, .16);
  border-radius: 50%;
  transform: translate(-50%, -50%);
}
.orbit-line-a { width: 74%; aspect-ratio: 1; animation: orbitGlow 6s ease-in-out infinite; }
.orbit-line-b { width: 52%; aspect-ratio: 1; border-style: dashed; animation: rotateRing 28s linear infinite; }
.orbit-core {
  position: absolute;
  left: 50%; top: 50%;
  display: grid;
  place-items: center;
  width: 148px; height: 148px;
  padding: 16px;
  border: 1px solid rgba(117, 94, 255, .24);
  border-radius: 50%;
  text-align: center;
  transform: translate(-50%, -50%);
  background:
    radial-gradient(circle at 35% 28%, rgba(255,255,255,.9), transparent 32%),
    linear-gradient(145deg, rgba(121,103,255,.18), rgba(68,179,255,.1));
  box-shadow: 0 22px 55px rgba(78, 59, 177, .17), inset 0 0 30px rgba(255,255,255,.28);
}
.orbit-core span, .orbit-core small { color: var(--app-text-muted); font-size: 11px; }
.orbit-core strong { max-width: 110px; font-size: 16px; line-height: 1.2; }

.agent-node {
  --orbit-radius: clamp(164px, 15vw, 205px);
  position: absolute;
  left: 50%; top: 50%;
  display: grid;
  grid-template-columns: 42px minmax(0, 86px) 22px;
  align-items: center;
  gap: 7px;
  min-width: 154px;
  padding: 8px 9px;
  border: 1px solid color-mix(in srgb, var(--app-border) 74%, transparent);
  border-radius: 18px;
  color: inherit;
  background: color-mix(in srgb, var(--app-surface) 92%, transparent);
  box-shadow: 0 10px 30px rgba(31, 27, 71, .09);
  cursor: pointer;
  transform:
    translate(-50%, -50%)
    rotate(var(--orbit-angle))
    translateX(var(--orbit-radius))
    rotate(calc(var(--orbit-angle) * -1));
  transition: border-color .2s ease, box-shadow .2s ease, scale .2s ease;
  animation: nodeFloat 4.2s ease-in-out var(--orbit-delay) infinite;
}
.agent-node:hover, .agent-node.active {
  border-color: rgba(117, 94, 255, .58);
  box-shadow: 0 15px 42px rgba(83, 61, 194, .18);
  scale: 1.05;
}
.is-dragging .agent-node { animation: dropPulse 1.15s ease-in-out var(--orbit-delay) infinite; }
.agent-avatar {
  display: grid; place-items: center;
  width: 42px; height: 42px;
  border-radius: 14px;
  color: white;
  font-weight: 800;
  background: linear-gradient(145deg, #826dff, #4baeea);
}
.agent-name { overflow: hidden; font-size: 12px; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }
.agent-count {
  display: grid; place-items: center;
  width: 22px; height: 22px;
  border-radius: 50%;
  color: #6b52e9;
  font-size: 11px;
  background: rgba(117, 94, 255, .11);
}
.agent-node.busy { opacity: .55; pointer-events: none; }
.agent-orbit.is-dense .agent-node {
  grid-template-columns: 36px minmax(0, 68px) 20px;
  min-width: 132px;
  gap: 5px;
  padding: 7px;
}
.agent-orbit.is-dense .agent-avatar {
  width: 36px;
  height: 36px;
  border-radius: 12px;
}
.agent-orbit.is-dense .agent-count {
  width: 20px;
  height: 20px;
}

.assembly-footer {
  position: absolute;
  left: 24px; right: 24px; bottom: 20px;
  display: flex; align-items: center; justify-content: center; gap: 8px;
  color: var(--app-text-muted);
  font-size: 12px;
}
.pulse-ring {
  width: 8px; height: 8px; border-radius: 50%; background: #795fff;
  box-shadow: 0 0 0 5px rgba(121,95,255,.1);
}

.bound-popover { width: 290px; padding: 4px; }
.bound-title { display: flex; justify-content: space-between; margin-bottom: 10px; }
.bound-title span { color: var(--app-text-muted); font-size: 11px; }
.bound-list { display: grid; gap: 6px; }
.bound-list > div {
  display: grid;
  grid-template-columns: 26px minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  padding: 7px;
  border-radius: 10px;
  background: var(--app-surface-soft);
}
.bound-kind { width: 26px; height: 26px; color: #6c54e6; background: rgba(117,94,255,.1); }

@keyframes rotateRing { to { transform: translate(-50%, -50%) rotate(360deg); } }
@keyframes orbitGlow { 50% { border-color: rgba(74,174,238,.28); box-shadow: 0 0 55px rgba(94,80,215,.08); } }
@keyframes nodeFloat { 50% { translate: 0 -5px; } }
@keyframes dropPulse { 50% { filter: brightness(1.08); } }
@keyframes hintPulse { 50% { transform: scale(1.04); } }

@media (max-width: 1100px) {
  .workbench-grid { grid-template-columns: 1fr; }
  .assembly-panel { min-height: 620px; }
  .agent-node { --orbit-radius: min(31vw, 205px); }
}

@media (prefers-reduced-motion: reduce) {
  .orbit-line-b, .agent-node, .drop-hint { animation: none !important; }
}
</style>
