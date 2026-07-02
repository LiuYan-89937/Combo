<template>
  <div class="tool-card" :class="[`status-${displayStatus}`]">
    <div class="tool-summary-row">
      <div class="tool-status-icon" :class="{ spinning: isRunning }" aria-hidden="true">
        <n-icon v-if="['approved', 'completed', 'observed'].includes(displayStatus)"><CheckmarkCircleOutline /></n-icon>
        <n-icon v-else-if="['failed', 'rejected'].includes(displayStatus)"><CloseCircleOutline /></n-icon>
        <n-icon v-else-if="displayStatus === 'approval'"><AlertCircleOutline /></n-icon>
      </div>
      <div class="tool-main">
        <div class="tool-title-line">
          <span class="tool-title">{{ displayName }}</span>
          <n-tag :type="statusTagType" size="small" :bordered="false">{{ statusText }}</n-tag>
        </div>
        <div class="tool-subtitle">{{ subtitle }}</div>
      </div>
      <n-button
        quaternary
        size="tiny"
        class="tool-expand-btn"
        :aria-expanded="expanded"
        @click="expanded = !expanded"
      >
        {{ expanded ? t('tool.collapse') : t('tool.details') }}
      </n-button>
    </div>

    <n-collapse-transition :show="expanded">
      <div class="tool-detail">
        <div v-if="argumentSummary" class="detail-block">
          <div class="detail-label">{{ t('tool.arguments') }}</div>
          <pre>{{ argumentSummary }}</pre>
        </div>
        <div v-if="outputSummary" class="detail-block">
          <div class="detail-label">{{ t('tool.result') }}</div>
          <pre>{{ outputSummary }}</pre>
        </div>
        <div v-if="errorSummary" class="detail-block error-block">
          <div class="detail-label">{{ t('tool.error') }}</div>
          <pre>{{ errorSummary }}</pre>
        </div>
        <div v-if="metaSummary" class="detail-meta">{{ metaSummary }}</div>
      </div>
    </n-collapse-transition>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { NButton, NCollapseTransition, NIcon, NTag } from 'naive-ui'
import {
  AlertCircleOutline,
  CheckmarkCircleOutline,
  CloseCircleOutline,
} from '@vicons/ionicons5'
import type { ToolActivity } from '@/types/protocol'
import { useI18n } from '@/composables/useI18n'
import { toolActivityDisplayStatus } from '@/utils/toolActivityState'

const props = defineProps<{
  tool: ToolActivity
}>()

const { t } = useI18n()
const expanded = ref(false)
const DETAIL_MAX_CHARS = 1600

const displayName = computed(() => friendlyToolName(props.tool.toolName))
const displayStatus = computed(() => toolActivityDisplayStatus(props.tool))
const isRunning = computed(() => ['proposed', 'started'].includes(props.tool.status))
const statusText = computed(() => {
  return {
    approved: t('tool.status.approved'),
    rejected: t('tool.status.rejected'),
    approval: t('tool.status.waitingApproval'),
    proposed: t('tool.status.proposed'),
    started: t('tool.status.started'),
    completed: t('tool.status.completed'),
    failed: t('tool.status.failed'),
    observed: t('tool.status.observed'),
  }[displayStatus.value] || displayStatus.value
})
const statusTagType = computed<'default' | 'success' | 'warning' | 'error' | 'info'>(() => {
  if (displayStatus.value === 'approved' || displayStatus.value === 'completed' || displayStatus.value === 'observed') return 'success'
  if (displayStatus.value === 'failed' || displayStatus.value === 'rejected') return 'error'
  if (displayStatus.value === 'approval') return 'warning'
  return 'info'
})
const subtitle = computed(() => {
  if (displayStatus.value === 'approval') return t('tool.subtitle.approval')
  if (displayStatus.value === 'approved') return t('tool.subtitle.approved')
  if (displayStatus.value === 'rejected') return t('tool.subtitle.rejected')
  if (isKnowledgeTool.value) return knowledgeSubtitle.value
  if (props.tool.status === 'started') return t('tool.subtitle.started')
  if (props.tool.status === 'completed' || props.tool.status === 'observed') return resultHeadline.value || t('tool.subtitle.completed')
  if (props.tool.status === 'failed') return errorHeadline.value || t('tool.subtitle.failed')
  return t('tool.subtitle.proposed')
})
const isKnowledgeTool = computed(() => String(props.tool.toolName || '').toLowerCase() === 'knowledge')
const knowledgeSubtitle = computed(() => {
  const args = recordValue(argumentValue.value)
  const action = String(args.action || props.tool.payload?.action || '').trim()
  if (props.tool.status === 'started' || props.tool.status === 'proposed') return t('factory.knowledgeRetrieving')
  if (action) return t('tool.knowledge.action', { action })
  return t('tool.knowledge.call')
})
const argumentValue = computed(() => normalizedValue(props.tool.payload?.arguments || props.tool.payload?.args))
const outputValue = computed(() => normalizedValue(
  props.tool.payload?.output ||
  props.tool.payload?.result ||
  props.tool.payload?.observation ||
  props.tool.payload?.content,
))
const errorValue = computed(() => normalizedValue(props.tool.payload?.error))
const argumentSummary = computed(() => compactString(argumentValue.value))
const outputSummary = computed(() => compactString(outputValue.value))
const errorSummary = computed(() => compactString(errorValue.value))
const resultHeadline = computed(() => headline(outputSummary.value))
const errorHeadline = computed(() => headline(errorSummary.value))
const metaSummary = computed(() => {
  const parts = []
  if (props.tool.toolCallId) parts.push(t('tool.meta.callId', { id: props.tool.toolCallId }))
  if (props.tool.nodeId) parts.push(t('tool.meta.node', { id: props.tool.nodeId }))
  return parts.join(' · ')
})

function friendlyToolName(name: string): string {
  const value = String(name || '').trim()
  if (!value) return t('tool.call')
  const labels: Record<string, string> = {
    knowledge: t('tool.name.knowledge'),
    bash: t('tool.name.bash'),
    web_search: t('tool.name.webSearch'),
    bigopen_web_search: t('tool.name.webSearch'),
    bigopen_web_crawl: t('tool.name.webCrawl'),
    runtime_plan: t('tool.name.runtimePlan'),
    tool_call: t('tool.call'),
  }
  return labels[value] || value
}

function normalizedValue(value: unknown): unknown {
  if (typeof value !== 'string') return value
  const text = value.trim()
  if (!text) return ''
  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}

function compactString(value: unknown): string {
  if (value == null || value === '') return ''
  const text = typeof value === 'string' ? value : JSON.stringify(value, null, 2) || String(value)
  if (text.length <= DETAIL_MAX_CHARS) return text
  return `${text.slice(0, DETAIL_MAX_CHARS).trimEnd()}\n${t('tool.outputCollapsed')}`
}

function headline(value: string): string {
  const line = value.split('\n').map((item) => item.trim()).find(Boolean) || ''
  return line.length > 88 ? `${line.slice(0, 88)}...` : line
}

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}
</script>

<style scoped>
.tool-card {
  position: relative;
  margin: var(--app-space-xs) var(--app-space-lg) var(--app-space-sm) 60px;
  padding: var(--app-space-md);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
  background: var(--app-surface-muted);
  transition: border-color var(--app-transition-fast), background-color var(--app-transition-fast);
  animation: app-fade-in-up 0.28s cubic-bezier(0.16, 1, 0.3, 1) both;
  overflow: hidden;
}

.tool-card::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background: var(--app-border);
  transition: background var(--app-transition-fast);
}

.tool-card.status-approved::before,
.tool-card.status-completed::before,
.tool-card.status-observed::before {
  background: var(--app-success);
}

.tool-card.status-failed::before,
.tool-card.status-rejected::before {
  background: var(--app-error);
}

.tool-card.status-approval::before {
  background: var(--app-warning);
}

.tool-card.status-proposed::before,
.tool-card.status-started::before {
  background: var(--app-info);
  animation: app-pulse-soft 1.6s ease-in-out infinite;
}

.tool-card:hover {
  border-color: var(--app-border-hover);
  background: var(--app-surface);
}

@media (max-width: 768px) {
  .tool-card {
    margin-left: var(--app-space-sm);
    margin-right: var(--app-space-sm);
  }
}

.tool-summary-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.tool-status-icon {
  width: 18px;
  height: 18px;
  flex: 0 0 18px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--app-text);
}

.tool-status-icon.spinning {
  border: 1px solid var(--app-border);
  border-top-color: var(--app-text);
  border-radius: 50%;
  animation: tool-spin 0.8s linear infinite;
}

.tool-main {
  min-width: 0;
  flex: 1;
}

.tool-title-line {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.tool-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--app-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tool-subtitle {
  margin-top: 3px;
  font-size: 12px;
  color: var(--app-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tool-detail {
  margin-top: var(--app-space-md);
  padding-top: var(--app-space-md);
  border-top: 1px solid var(--app-divider);
  display: flex;
  flex-direction: column;
  gap: var(--app-space-md);
  animation: app-fade-in 0.24s ease both;
}

.tool-expand-btn {
  flex-shrink: 0;
}

.detail-label {
  margin-bottom: 4px;
  font-size: 12px;
  font-weight: 600;
  color: var(--app-text-secondary);
}

pre {
  max-height: 260px;
  margin: 0;
  padding: 10px 12px;
  overflow: auto;
  border-radius: 6px;
  background: var(--app-code-background);
  border: 1px solid var(--app-code-border);
  color: var(--app-text);
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}

.error-block pre {
  border: 1px solid var(--app-error);
}

.detail-meta {
  font-size: 12px;
  color: var(--app-text-muted);
}

@keyframes tool-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
