<template>
  <div class="sidebar-content">
    <section class="status-section">
      <div class="section-title">上下文</div>
      <div v-if="contextWindow" class="context-meter">
        <div class="context-meter-row">
          <span class="context-meter-label">窗口用量</span>
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
      <n-empty v-else description="暂无上下文用量" size="small" />
    </section>

    <section class="status-section">
      <div class="section-title">活动</div>
      <n-empty v-if="runtimeStore.timeline.length === 0" description="暂无活动" size="small" />
      <div v-else class="timeline-list">
        <div
          v-for="item in recentTimeline"
          :key="item.id"
          class="timeline-item"
        >
          <div class="timeline-time">
            {{ formatTime(item.timestamp) }}
          </div>
          <div class="timeline-content">
            <strong>{{ item.nodeLabel || item.eventType }}</strong>
            <div v-if="item.message" class="timeline-message">
              {{ item.message }}
            </div>
          </div>
        </div>
      </div>
    </section>

    <section class="status-section">
      <div class="section-title">工具</div>
      <n-empty v-if="runtimeStore.tools.length === 0" description="暂无工具调用" size="small" />
      <div v-else class="tools-list">
        <div
          v-for="tool in runtimeStore.tools"
          :key="tool.activityKey"
          class="tool-item"
        >
          <n-tag :type="toolStatusType(tool.status)" size="small">
            {{ tool.status }}
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
import { useRuntimeStore } from '@/stores/runtime'
import {
  contextWindowPercentLabel,
  contextWindowThresholdPercent,
  contextWindowThresholdLabel,
  contextWindowUsageLabel,
  contextWindowUsagePercent,
} from '@/utils/contextWindowMeter'

const runtimeStore = useRuntimeStore()

const recentTimeline = computed(() => runtimeStore.timeline.slice(-20).reverse())
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
  contextWindow.value ? contextWindowPercentLabel(contextWindow.value) : '用量未知'
))
const contextWindowThresholdText = computed(() => (
  contextWindow.value ? contextWindowThresholdLabel(contextWindow.value) : '压缩阈值 -'
))
const contextThresholdMarker = computed(() => {
  if (!contextWindow.value) return ''
  const percent = contextWindowThresholdPercent(contextWindow.value)
  return percent === null ? '' : `${percent}%`
})
function formatTime(timestamp: string): string {
  const date = new Date(timestamp)
  return date.toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

function toolStatusType(status: string): 'default' | 'success' | 'warning' | 'error' | 'info' {
  const types: Record<string, any> = {
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

.timeline-list,
.tools-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.timeline-item {
  display: flex;
  gap: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--n-border-color);
}

.timeline-time {
  flex-shrink: 0;
  font-size: 12px;
  color: var(--n-text-color-3);
  width: 80px;
}

.timeline-content {
  flex: 1;
  font-size: 14px;
}

.timeline-message {
  margin-top: 4px;
  font-size: 13px;
  color: var(--n-text-color-2);
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
