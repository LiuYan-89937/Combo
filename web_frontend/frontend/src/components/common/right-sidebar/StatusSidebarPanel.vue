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
  padding: 16px;
  overflow-y: auto;
  height: 100%;
}

.status-section {
  padding-bottom: 16px;
  margin-bottom: 16px;
  border-bottom: 1px solid var(--n-border-color);
}

.status-section:last-child {
  margin-bottom: 0;
  border-bottom: 0;
}

.section-title {
  margin-bottom: 12px;
  font-size: 13px;
  font-weight: 600;
  color: var(--n-text-color-1);
}

.context-meter {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.context-meter-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  font-size: 13px;
}

.context-meter-label {
  color: var(--n-text-color-2);
}

.context-meter-value {
  flex-shrink: 0;
  color: #111111;
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
  background: #e7e7e7;
  box-shadow: inset 0 0 0 1px #d7d7d7;
}

.context-meter-track.unknown {
  background: repeating-linear-gradient(
    90deg,
    #eeeeee 0,
    #eeeeee 6px,
    #d8d8d8 6px,
    #d8d8d8 8px
  );
}

.context-meter-fill {
  height: 100%;
  border-radius: inherit;
  background: #111111;
  transition: width 0.2s ease;
}

.context-meter-marker {
  position: absolute;
  top: -5px;
  bottom: -5px;
  width: 2px;
  border-radius: 999px;
  background: #777777;
  opacity: 0.85;
}

.context-meter-detail {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 11px;
  line-height: 16px;
  color: var(--n-text-color-3);
}

.tools-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.tool-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px;
  border-radius: 4px;
  background-color: var(--n-color-embedded);
}

.tool-name {
  font-size: 13px;
  font-family: monospace;
}
</style>
