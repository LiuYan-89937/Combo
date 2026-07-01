<template>
  <div class="sidebar-content">
    <section class="status-section">
      <div class="section-title">上下文</div>
      <div v-if="contextWindow" class="context-meter">
        <div class="context-meter-row">
          <span class="context-meter-label">窗口用量</span>
          <span class="context-meter-value">{{ contextWindowPercentText }}</span>
        </div>
        <div class="context-meter-track" aria-hidden="true">
          <div class="context-meter-fill" :style="{ width: contextWindowBarWidth }"></div>
          <div
            v-if="contextThresholdMarker"
            class="context-meter-marker"
            :style="{ left: contextThresholdMarker }"
          ></div>
        </div>
        <div class="context-meter-meta">
          {{ formatTokenCount(contextWindow.tokenCount) }} / {{ formatTokenCount(contextWindow.contextWindowTokens) }} tokens
        </div>
        <div class="context-meter-meta muted">
          压缩阈值 {{ formatTokenCount(contextWindow.compressionThresholdTokens) }}
          <span v-if="contextWindow.tokenCountMethod"> · {{ contextTokenMethodText }}</span>
        </div>
        <div class="context-meter-status">
          {{ contextStatusText }}
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

const runtimeStore = useRuntimeStore()

const recentTimeline = computed(() => runtimeStore.timeline.slice(-20).reverse())
const contextWindow = computed(() => runtimeStore.contextWindow)
const contextWindowPercent = computed(() => ratioToPercent(contextWindow.value?.windowUsageRatio))
const contextWindowPercentText = computed(() => (
  typeof contextWindow.value?.windowUsageRatio === 'number'
    ? formatPercent(contextWindowPercent.value)
    : contextWindow.value?.tokenCount !== null && contextWindow.value?.tokenCount !== undefined
      ? '已记录'
      : '暂无'
))
const contextWindowBarWidth = computed(() => `${contextWindowPercent.value}%`)
const contextThresholdMarker = computed(() => {
  const windowTokens = contextWindow.value?.contextWindowTokens
  const thresholdTokens = contextWindow.value?.compressionThresholdTokens
  if (!windowTokens || !thresholdTokens) return ''
  return `${Math.min(100, Math.max(0, (thresholdTokens / windowTokens) * 100))}%`
})
const contextStatusText = computed(() => {
  const activity = runtimeStore.contextActivity
  if (!activity?.eventType) return '等待上下文事件'
  const labels: Record<string, string> = {
    context_prepare_started: '正在准备上下文',
    context_prepare_completed: '上下文已准备',
    context_prepare_failed: '上下文准备失败',
    context_compression_started: '正在压缩上下文',
    context_compression_completed: '上下文已压缩',
    context_compression_failed: '上下文压缩失败',
    context_compression_skipped: '未触发上下文压缩',
    context_window_updated: '上下文窗口已更新',
    context_retrieval_completed: '上下文检索已完成',
    context_assembly_completed: '上下文组装已完成',
    context_injection_completed: '上下文注入已完成',
  }
  return labels[activity.eventType] || activity.eventType
})
const contextTokenMethodText = computed(() => {
  const method = contextWindow.value?.tokenCountMethod
  const labels: Record<string, string> = {
    provider_usage: '模型返回用量',
    previous_provider_usage: '上次模型用量',
    local_counter: '本地计数',
    unavailable: '无法计数',
  }
  return method ? labels[method] || method : ''
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

function ratioToPercent(ratio: number | null | undefined): number {
  if (typeof ratio !== 'number' || !Number.isFinite(ratio)) return 0
  return Math.min(100, Math.max(0, ratio * 100))
}

function formatPercent(value: number): string {
  if (value >= 10) return `${value.toFixed(1)}%`
  if (value > 0) return `${value.toFixed(2)}%`
  return '0%'
}

function formatTokenCount(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '-'
  return new Intl.NumberFormat('zh-CN').format(Math.round(value))
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
  gap: 8px;
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
  color: var(--n-text-color-1);
  font-weight: 600;
}

.context-meter-track {
  position: relative;
  height: 8px;
  overflow: hidden;
  border: 1px solid var(--n-border-color);
  border-radius: 999px;
  background: var(--n-color-embedded);
}

.context-meter-fill {
  height: 100%;
  border-radius: inherit;
  background: var(--n-text-color-1);
  transition: width 0.2s ease;
}

.context-meter-marker {
  position: absolute;
  top: -3px;
  bottom: -3px;
  width: 1px;
  background: var(--n-text-color-3);
}

.context-meter-meta,
.context-meter-status {
  font-size: 12px;
  color: var(--n-text-color-2);
}

.context-meter-meta.muted {
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
