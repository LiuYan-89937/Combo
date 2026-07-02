<template>
  <div class="sidebar-content">
    <section class="status-section">
      <div class="section-title">{{ t('status.context') }}</div>
      <div v-if="contextWindow" class="context-meter">
        <div class="context-meter-row">
          <span class="context-meter-label">{{ t('status.windowUsage') }}</span>
          <span class="context-meter-value">{{ contextWindowUsageText }}</span>
        </div>
        <div class="context-meter-track" :class="{ unknown: contextWindowPercent === null }" aria-hidden="true">
          <div
            v-if="contextWindowPercent !== null"
            class="context-meter-fill"
            :style="{ width: contextWindowFillWidth }"
          ></div>
          <div
            v-if="contextThresholdMarker"
            class="context-meter-marker"
            :style="{ left: contextThresholdMarker }"
          ></div>
        </div>
        <div class="context-meter-detail">
          <span>{{ contextWindowPercentText }}</span>
          <span>{{ contextWindowThresholdText }}</span>
        </div>
      </div>
      <n-empty v-else :description="t('status.noContext')" size="small" />
    </section>

    <section v-if="runtimeStore.currentPlan" class="status-section">
      <div class="section-title">{{ t('right.plan') }}</div>
      <PlanPanel compact />
    </section>

    <section class="status-section">
      <div class="section-title">{{ t('status.tools') }}</div>
      <n-empty v-if="runtimeStore.tools.length === 0" :description="t('status.noTools')" size="small" />
      <div v-else class="tools-list">
        <div
          v-for="tool in runtimeStore.tools"
          :key="tool.activityKey"
          class="tool-item"
        >
          <n-tag :type="toolStatusType(tool)" size="small">
            {{ toolStatusLabel(tool) }}
          </n-tag>
          <span class="tool-name">{{ tool.toolName }}</span>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NEmpty, NTag } from 'naive-ui'
import { useI18n } from '@/composables/useI18n'
import { useRuntimeStore } from '@/stores/runtime'
import PlanPanel from '@/components/plan/PlanPanel.vue'
import type { ToolActivity } from '@/types/protocol'
import { toolActivityDisplayStatus, type ToolActivityDisplayStatus } from '@/utils/toolActivityState'
import {
  contextWindowPercentLabel,
  contextWindowThresholdPercent,
  contextWindowThresholdLabel,
  contextWindowUsageLabel,
  contextWindowUsagePercent,
} from '@/utils/contextWindowMeter'

const runtimeStore = useRuntimeStore()
const { t } = useI18n()

const contextWindow = computed(() => runtimeStore.contextWindow)
const contextWindowPercent = computed(() => (
  contextWindow.value ? contextWindowUsagePercent(contextWindow.value) : null
))
const contextWindowFillWidth = computed(() => (
  contextWindowPercent.value === null ? '0%' : `${contextWindowPercent.value}%`
))
const contextWindowUsageText = computed(() => (
  contextWindow.value ? contextWindowUsageLabel(contextWindow.value) : '- / -'
))
const contextWindowPercentText = computed(() => (
  contextWindow.value ? contextWindowPercentLabel(contextWindow.value, contextWindowLabels.value) : t('status.waitContextEvent')
))
const contextWindowThresholdText = computed(() => (
  contextWindow.value ? contextWindowThresholdLabel(contextWindow.value, contextWindowLabels.value) : t('status.compressionThreshold', { tokens: '-' })
))
const contextWindowLabels = computed(() => ({
  unknownUsage: t('status.waitContextEvent'),
  used: t('status.recorded'),
  compressionThreshold: t('status.compressionThreshold', { tokens: '' }).trim(),
}))
const contextThresholdMarker = computed(() => {
  if (!contextWindow.value) return ''
  const percent = contextWindowThresholdPercent(contextWindow.value)
  return percent === null ? '' : `${percent}%`
})

function toolStatusLabel(tool: ToolActivity): string {
  const status = toolActivityDisplayStatus(tool)
  const labels: Record<ToolActivityDisplayStatus, string> = {
    approved: t('tool.status.approved'),
    rejected: t('tool.status.rejected'),
    proposed: t('tool.status.proposed'),
    approval: t('tool.status.waitingApproval'),
    started: t('tool.status.started'),
    completed: t('tool.status.completed'),
    failed: t('tool.status.failed'),
    observed: t('tool.status.observed'),
  }
  return labels[status] || t('common.unknown')
}

function toolStatusType(tool: ToolActivity): 'default' | 'success' | 'warning' | 'error' | 'info' {
  const status = toolActivityDisplayStatus(tool)
  const types: Record<ToolActivityDisplayStatus, 'default' | 'success' | 'warning' | 'error' | 'info'> = {
    approved: 'success',
    rejected: 'error',
    proposed: 'default',
    approval: 'warning',
    started: 'info',
    completed: 'success',
    failed: 'error',
    observed: 'success',
  }
  return types[status] || 'default'
}

</script>

<style scoped>
.sidebar-content {
  padding: var(--app-space-lg);
  overflow-y: auto;
  height: 100%;
}

.status-section {
  padding-bottom: var(--app-space-lg);
  margin-bottom: var(--app-space-lg);
  border-bottom: 1px solid var(--app-divider);
}

.status-section:last-child {
  margin-bottom: 0;
  border-bottom: 0;
}

.section-title {
  margin-bottom: var(--app-space-md);
  font-size: var(--app-font-md);
  font-weight: 600;
  color: var(--app-text);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.context-meter {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-md);
}

.context-meter-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-md);
  font-size: var(--app-font-md);
}

.context-meter-label {
  color: var(--app-text-secondary);
}

.context-meter-value {
  flex-shrink: 0;
  color: var(--app-text);
  font-size: 13px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.context-meter-track {
  position: relative;
  width: 100%;
  height: 6px;
  overflow: hidden;
  border-radius: 999px;
  background: var(--app-surface-muted);
  box-shadow: inset 0 0 0 1px var(--app-border);
}

.context-meter-track.unknown {
  background: repeating-linear-gradient(
    90deg,
    var(--app-surface-muted) 0,
    var(--app-surface-muted) 6px,
    var(--app-border) 6px,
    var(--app-border) 8px
  );
}

.context-meter-fill {
  height: 100%;
  border-radius: inherit;
  background: var(--app-text);
  transition: width 0.2s ease;
}

.context-meter-marker {
  position: absolute;
  top: -5px;
  bottom: -5px;
  width: 2px;
  border-radius: 999px;
  background: var(--app-text-muted);
  opacity: 0.85;
}

.context-meter-detail {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-sm);
  font-size: var(--app-font-xs);
  line-height: 16px;
  color: var(--app-text-muted);
  font-variant-numeric: tabular-nums;
}

.tools-list {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-sm);
}

.tool-item {
  display: flex;
  align-items: center;
  gap: var(--app-space-sm);
  padding: var(--app-space-sm) var(--app-space-md);
  border-radius: var(--app-radius-md);
  background-color: var(--app-surface-muted);
  border: 1px solid var(--app-border);
  transition: border-color var(--app-transition-fast), background-color var(--app-transition-fast);
}

.tool-item:hover {
  border-color: var(--app-border-hover);
  background: var(--app-surface-hover);
}

.tool-name {
  font-size: var(--app-font-md);
  font-family: 'SF Mono', Monaco, 'Cascadia Code', 'Roboto Mono', monospace;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
  flex: 1;
}
</style>
