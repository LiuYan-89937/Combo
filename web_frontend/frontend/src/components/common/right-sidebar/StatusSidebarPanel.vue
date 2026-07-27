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
      <div
        v-if="compressionActivityText"
        class="compression-activity"
        :class="compressionActivityClass"
        role="status"
        aria-live="polite"
      >
        <span v-if="runtimeStore.contextActivity.status === 'running'" class="compression-pulse"></span>
        <span>{{ compressionActivityText }}</span>
      </div>
    </section>

    <section v-if="activeRuntimeRequest" class="status-section">
      <div class="section-heading">
        <div class="section-title compact">{{ t('status.currentRequest') }}</div>
        <n-tag size="small" type="info" :bordered="false">
          {{ t('status.requestRunning') }}
        </n-tag>
      </div>
      <div class="request-status">
        <div class="request-status-row">
          <span>{{ t('status.requestElapsed') }}</span>
          <strong>{{ t('status.seconds', { count: requestElapsedSeconds }) }}</strong>
        </div>
        <div class="request-status-row">
          <span>{{ t('status.requestTimeout') }}</span>
          <strong>{{ requestTimeoutText }}</strong>
        </div>
        <div v-if="requestTimeoutSeconds !== null && requestTimeoutSeconds > 0" class="request-progress" aria-hidden="true">
          <div class="request-progress-fill" :style="{ width: requestProgressWidth }"></div>
        </div>
      </div>
    </section>

    <section class="status-section">
      <div class="section-heading">
        <div class="section-title compact">{{ t('status.memory') }}</div>
        <n-button
          quaternary
          circle
          size="small"
          :loading="memoryLoading"
          :title="t('status.memoryRefresh')"
          @click="refreshMemory"
        >
          <template #icon>
            <n-icon><RefreshOutline /></n-icon>
          </template>
        </n-button>
      </div>

      <div class="memory-activity" :class="memoryActivityClass">
        <span v-if="runtimeStore.memoryActivity.status === 'writing'" class="memory-pulse"></span>
        <span>{{ memoryActivityText }}</span>
      </div>

      <div class="memory-query">
        <n-input
          v-model:value="memoryQuery"
          size="small"
          clearable
          :placeholder="t('status.memoryQueryPlaceholder')"
          @keyup.enter="refreshMemory"
        />
        <n-button secondary size="small" :loading="memoryLoading" @click="refreshMemory">
          <template #icon>
            <n-icon><SearchOutline /></n-icon>
          </template>
        </n-button>
      </div>

      <div v-if="memoryError" class="memory-error">{{ memoryError }}</div>

      <n-spin :show="memoryLoading" size="small">
        <n-empty
          v-if="!memoryItems.length && !memoryLoading"
          :description="t('status.memoryEmpty')"
          size="small"
        />
        <div v-else class="memory-list">
          <div v-for="item in memoryItems" :key="item.memory_id" class="memory-item">
            <div class="memory-item-header">
              <n-tag size="small" :bordered="false">{{ memoryKindLabel(item.kind) }}</n-tag>
              <span class="memory-score">{{ t('status.memoryScore', { score: percentLabel(item.score) }) }}</span>
              <n-popconfirm
                :positive-text="t('common.delete')"
                :negative-text="t('common.cancel')"
                @positive-click="deleteMemoryItem(item.memory_id)"
              >
                <template #trigger>
                  <n-button
                    quaternary
                    circle
                    size="tiny"
                    :loading="isDeletingMemory(item.memory_id)"
                    :title="t('status.memoryDelete')"
                  >
                    <template #icon>
                      <n-icon><TrashOutline /></n-icon>
                    </template>
                  </n-button>
                </template>
                {{ t('status.memoryDeleteConfirm') }}
              </n-popconfirm>
            </div>
            <div class="memory-content">{{ item.content }}</div>
            <div class="memory-meta">
              <span v-if="memoryConfidence(item) !== null">
                {{ t('status.memoryConfidence', { score: percentLabel(memoryConfidence(item)) }) }}
              </span>
              <span v-if="item.updated_at">{{ formatMemoryTime(item.updated_at) }}</span>
            </div>
          </div>
        </div>
      </n-spin>
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
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { NButton, NEmpty, NIcon, NInput, NPopconfirm, NSpin, NTag } from 'naive-ui'
import { RefreshOutline, SearchOutline, TrashOutline } from '@/components/icons'
import { memoryApi, type MemoryContextItemView } from '@/api/memory'
import { useI18n } from '@/composables/useI18n'
import { useResourceContext } from '@/composables/useResourceContext'
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
  formatCompactTokenCount,
} from '@/utils/contextWindowMeter'

const runtimeStore = useRuntimeStore()
const resourceContext = useResourceContext()
const { t } = useI18n()
const memoryQuery = ref('')
const memoryItems = ref<MemoryContextItemView[]>([])
const memoryLoading = ref(false)
const memoryError = ref('')
const deletingMemoryIds = ref<Record<string, boolean>>({})
const requestClock = ref(Date.now())
let memoryRequestSerial = 0
let requestClockTimer: number | null = null

const activeRuntimeRequest = computed(() => {
  const requestId = runtimeStore.activeRequestId
  if (!requestId) return null
  const request = runtimeStore.activeRequests[requestId]
  if (!request || request.background || request.status !== 'running') return null
  return request
})
const requestRuntimeNode = computed(() => runtimeStore.nodes.runtime_request || null)
const requestTimeoutSeconds = computed<number | null>(() => {
  const heartbeatTimeout = nonNegativeNumber(requestRuntimeNode.value?.payload?.timeout_seconds)
  if (heartbeatTimeout !== null) return heartbeatTimeout
  return nonNegativeNumber(activeRuntimeRequest.value?.payload?.runtime_request?.timeout_seconds)
})
const requestElapsedSeconds = computed(() => {
  const heartbeatElapsed = nonNegativeNumber(requestRuntimeNode.value?.payload?.elapsed_seconds) || 0
  const startedAt = Date.parse(activeRuntimeRequest.value?.startedAt || '')
  const localElapsed = Number.isFinite(startedAt)
    ? Math.max(0, Math.floor((requestClock.value - startedAt) / 1000))
    : 0
  return Math.floor(Math.max(heartbeatElapsed, localElapsed))
})
const requestTimeoutText = computed(() => {
  const timeout = requestTimeoutSeconds.value
  if (timeout === null) return t('status.requestTimeoutPending')
  if (timeout === 0) return t('status.requestNoTimeout')
  return t('status.seconds', { count: timeout })
})
const requestProgressWidth = computed(() => {
  const timeout = requestTimeoutSeconds.value
  if (timeout === null || timeout <= 0) return '0%'
  return `${Math.min(100, (requestElapsedSeconds.value / timeout) * 100)}%`
})

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
const compressionActivityText = computed(() => {
  const activity = runtimeStore.contextActivity
  const payload = activity.payload || {}
  if (activity.status === 'running') {
    return t('status.contextCompressionRunning', {
      before: formatCompactTokenCount(optionalNumber(payload.token_estimate_before)),
    })
  }
  if (activity.status === 'completed') {
    return t('status.contextCompressionCompleted', {
      before: formatCompactTokenCount(optionalNumber(payload.token_estimate_before)),
      after: formatCompactTokenCount(optionalNumber(payload.token_estimate_after)),
      count: Number(payload.original_message_count || 0) - Number(payload.compressed_message_count || 0),
    })
  }
  if (activity.status === 'failed') {
    return t('status.contextCompressionFailed', {
      reason: String(payload.error || t('common.unknown')),
    })
  }
  return ''
})
const compressionActivityClass = computed(() => ({
  running: runtimeStore.contextActivity.status === 'running',
  completed: runtimeStore.contextActivity.status === 'completed',
  failed: runtimeStore.contextActivity.status === 'failed',
}))
const memoryActivityText = computed(() => {
  const activity = runtimeStore.memoryActivity
  const payload = activity.payload || {}
  if (activity.status === 'writing') {
    return t('status.memoryWriting')
  }
  if (activity.status === 'failed') {
    return payload.error ? t('status.memoryFailedWithReason', { reason: String(payload.error) }) : t('status.memoryFailed')
  }
  if (activity.eventType === 'memory_retrieval_completed' || activity.eventType === 'memory_injection_completed') {
    return t('status.memoryRetrieved', { count: Number(payload.item_count || 0) })
  }
  if (activity.eventType === 'memory_write_completed') {
    return t('status.memoryWriteCompleted')
  }
  return t('status.memoryIdle')
})
const memoryActivityClass = computed(() => ({
  writing: runtimeStore.memoryActivity.status === 'writing',
  failed: runtimeStore.memoryActivity.status === 'failed',
  completed: runtimeStore.memoryActivity.status === 'completed',
}))

async function refreshMemory() {
  const serial = ++memoryRequestSerial
  memoryLoading.value = true
  memoryError.value = ''
  try {
    const response = await memoryApi.query(
      memoryQuery.value.trim(),
      resourceContext.packageIdForApi.value,
      8,
    )
    if (serial !== memoryRequestSerial) return
    memoryItems.value = [...(response.items || [])].sort(memorySort)
  } catch (error) {
    if (serial !== memoryRequestSerial) return
    memoryItems.value = []
    memoryError.value = error instanceof Error ? error.message : String(error)
  } finally {
    if (serial === memoryRequestSerial) {
      memoryLoading.value = false
    }
  }
}

async function deleteMemoryItem(memoryId: string) {
  deletingMemoryIds.value = { ...deletingMemoryIds.value, [memoryId]: true }
  memoryError.value = ''
  try {
    await memoryApi.deleteItem(memoryId, resourceContext.packageIdForApi.value)
    memoryItems.value = memoryItems.value.filter((item) => item.memory_id !== memoryId)
    await refreshMemory()
  } catch (error) {
    memoryError.value = error instanceof Error ? error.message : String(error)
  } finally {
    const next = { ...deletingMemoryIds.value }
    delete next[memoryId]
    deletingMemoryIds.value = next
  }
}

function isDeletingMemory(memoryId: string): boolean {
  return Boolean(deletingMemoryIds.value[memoryId])
}

function memorySort(a: MemoryContextItemView, b: MemoryContextItemView): number {
  const scoreDiff = numericScore(b.score) - numericScore(a.score)
  if (scoreDiff !== 0) return scoreDiff
  return String(b.updated_at || '').localeCompare(String(a.updated_at || ''))
}

function numericScore(value: unknown): number {
  const score = Number(value)
  return Number.isFinite(score) ? score : 0
}

function memoryConfidence(item: MemoryContextItemView): number | null {
  const score = Number(item.metadata?.confidence)
  return Number.isFinite(score) ? score : null
}

function percentLabel(value: unknown): string {
  return `${Math.round(numericScore(value) * 100)}%`
}

function nonNegativeNumber(value: unknown): number | null {
  const numberValue = Number(value)
  return Number.isFinite(numberValue) && numberValue >= 0 ? numberValue : null
}

function optionalNumber(value: unknown): number | null {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function memoryKindLabel(kind: string): string {
  if (kind === 'preference') return t('status.memoryKind.preference')
  if (kind === 'decision') return t('status.memoryKind.decision')
  if (kind === 'constraint') return t('status.memoryKind.constraint')
  if (kind === 'artifact') return t('status.memoryKind.artifact')
  if (kind === 'fact') return t('status.memoryKind.fact')
  return kind || t('common.unknown')
}

function formatMemoryTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

onMounted(() => {
  refreshMemory()
})

onBeforeUnmount(() => {
  stopRequestClock()
})

watch(
  activeRuntimeRequest,
  (request) => {
    requestClock.value = Date.now()
    stopRequestClock()
    if (request) {
      requestClockTimer = window.setInterval(() => {
        requestClock.value = Date.now()
      }, 1000)
    }
  },
  { immediate: true },
)

watch(
  () => resourceContext.packageIdForApi.value,
  () => refreshMemory(),
)

watch(
  () => memoryActivityFingerprint(runtimeStore.memoryActivity),
  () => {
    const eventType = runtimeStore.memoryActivity.eventType
    if (eventType === 'memory_write_completed' || eventType === 'memory_write_failed') {
      refreshMemory()
    }
  },
)

function memoryActivityFingerprint(activity: { eventType?: string, payload?: Record<string, any> }): string {
  const payload = activity.payload || {}
  return [
    activity.eventType || '',
    payload.job_id || '',
    payload.duration_ms || '',
    payload.updated_at || '',
  ].join(':')
}

function stopRequestClock() {
  if (requestClockTimer === null) return
  window.clearInterval(requestClockTimer)
  requestClockTimer = null
}

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

.section-title.compact {
  margin-bottom: 0;
}

.section-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-sm);
  margin-bottom: var(--app-space-md);
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

.compression-activity {
  display: flex;
  align-items: flex-start;
  gap: var(--app-space-sm);
  margin-top: var(--app-space-md);
  padding: var(--app-space-sm) var(--app-space-md);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  color: var(--app-text-secondary);
  background: var(--app-surface-muted);
  font-size: var(--app-font-sm);
  line-height: 1.5;
}

.compression-activity.running {
  color: var(--app-text);
  border-color: var(--app-border-hover);
}

.compression-activity.completed {
  color: var(--app-success);
  border-color: color-mix(in srgb, var(--app-success) 35%, var(--app-border));
}

.compression-activity.failed {
  color: var(--app-error);
  border-color: color-mix(in srgb, var(--app-error) 35%, var(--app-border));
}

.compression-pulse {
  width: 7px;
  height: 7px;
  flex: 0 0 auto;
  margin-top: 6px;
  border-radius: 999px;
  background: currentColor;
  animation: memory-pulse 1s ease-in-out infinite;
}

.request-status {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-sm);
  padding: var(--app-space-md);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  background: var(--app-surface-muted);
}

.request-status-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-md);
  color: var(--app-text-secondary);
  font-size: var(--app-font-sm);
}

.request-status-row strong {
  color: var(--app-text);
  font-variant-numeric: tabular-nums;
}

.request-progress {
  height: 4px;
  overflow: hidden;
  border-radius: 999px;
  background: var(--app-border);
}

.request-progress-fill {
  height: 100%;
  border-radius: inherit;
  background: var(--app-text);
  transition: width 0.2s ease;
}

.memory-activity {
  display: flex;
  align-items: center;
  gap: var(--app-space-sm);
  min-height: 26px;
  padding: var(--app-space-xs) var(--app-space-sm);
  margin-bottom: var(--app-space-md);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  color: var(--app-text-muted);
  background: var(--app-surface-muted);
  font-size: var(--app-font-sm);
  line-height: 18px;
}

.memory-activity.writing {
  color: var(--app-text);
  border-color: var(--app-text-muted);
}

.memory-activity.failed {
  color: var(--app-error);
  border-color: color-mix(in srgb, var(--app-error) 35%, var(--app-border));
}

.memory-pulse {
  width: 7px;
  height: 7px;
  flex: 0 0 auto;
  border-radius: 999px;
  background: currentColor;
  animation: memory-pulse 1s ease-in-out infinite;
}

.memory-query {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: var(--app-space-sm);
  margin-bottom: var(--app-space-md);
}

.memory-error {
  margin-bottom: var(--app-space-md);
  color: var(--app-error);
  font-size: var(--app-font-sm);
  line-height: 18px;
}

.memory-list {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-sm);
}

.memory-item {
  padding: var(--app-space-sm);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  background: var(--app-surface);
}

.memory-item-header {
  display: flex;
  align-items: center;
  gap: var(--app-space-sm);
  margin-bottom: var(--app-space-xs);
}

.memory-score {
  min-width: 0;
  flex: 1;
  color: var(--app-text-muted);
  font-size: var(--app-font-xs);
  font-variant-numeric: tabular-nums;
  text-align: right;
}

.memory-content {
  color: var(--app-text);
  font-size: var(--app-font-sm);
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
}

.memory-meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--app-space-sm);
  margin-top: var(--app-space-xs);
  color: var(--app-text-muted);
  font-size: var(--app-font-xs);
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

@keyframes memory-pulse {
  0%,
  100% {
    opacity: 0.35;
    transform: scale(0.86);
  }
  50% {
    opacity: 1;
    transform: scale(1);
  }
}
</style>
