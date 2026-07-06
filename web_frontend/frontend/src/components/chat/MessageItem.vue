<template>
  <div class="message-item" :class="[`role-${message.role}`, { streaming }]">
    <div class="message-avatar">
      <n-avatar :size="36" :style="avatarStyle">
        {{ avatarText }}
      </n-avatar>
    </div>

    <div class="message-content">
      <div class="message-header">
        <n-text strong>{{ roleLabel }}</n-text>
        <n-text depth="3" style="font-size: 12px">
          {{ formatTime(message.timestamp) }}
        </n-text>
      </div>

      <div class="message-body">
        <div
          v-if="collaborationReport"
          class="collaboration-report-card"
        >
          <div class="collaboration-report-title">
            <span class="collaboration-report-dot" aria-hidden="true"></span>
            <span>{{ collaborationReportTitle }}</span>
          </div>
          <div class="collaboration-report-meta">
            <span>{{ collaborationReportStatus }}</span>
            <span v-if="collaborationReport.task_id">{{ t('collaboration.reportTask', { id: shortId(collaborationReport.task_id) }) }}</span>
            <span v-if="collaborationReport.artifact_count">{{ t('collaboration.reportArtifacts', { count: collaborationReport.artifact_count }) }}</span>
          </div>
          <div v-if="collaborationReport.summary" class="collaboration-report-summary">
            {{ compactSummary(collaborationReport.summary) }}
          </div>
        </div>
        <div
          v-else-if="thinking"
          class="thinking-content"
          role="status"
          aria-live="polite"
          :aria-label="t('roles.assistantThinking')"
        >
          <span class="thinking-dot"></span>
          <span class="thinking-dot"></span>
          <span class="thinking-dot"></span>
        </div>
        <template v-else>
          <MessagePartRenderer
            v-for="part in visibleParts"
            :key="part.id"
            :part="part"
            :streaming="streaming"
          />
        </template>

        <span
          v-if="streaming && !thinking"
          class="streaming-caret"
          aria-hidden="true"
        ></span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { CSSProperties } from 'vue'
import { NAvatar, NText } from 'naive-ui'
import { useI18n } from '@/composables/useI18n'
import MessagePartRenderer from './MessagePartRenderer.vue'
import type { TranscriptItem } from '@/types/protocol'

const props = withDefaults(
  defineProps<{
    message: TranscriptItem
    streaming?: boolean
    thinking?: boolean
  }>(),
  {
    streaming: false,
    thinking: false,
  }
)

const { locale, t } = useI18n()

const roleLabel = computed(() => {
  if (collaborationReport.value) return collaborationReportTitle.value
  if (props.message.role === 'user') return t('roles.user')
  if (props.message.role === 'system') return t('roles.system')
  return t('roles.assistant')
})

const avatarStyle = computed<CSSProperties>(() => {
  if (collaborationReport.value) {
    return {
      background: 'var(--app-surface-muted)',
      color: 'var(--app-text)',
      border: '1px solid var(--app-border-hover)',
    }
  }
  if (props.message.role === 'assistant') {
    return {
      background: 'var(--app-surface)',
      color: 'var(--app-text)',
      border: '1px solid var(--app-text)',
    }
  }
  return {
    background: 'var(--app-text)',
    color: 'var(--app-text-inverse)',
  }
})

const avatarText = computed(() => {
  if (collaborationReport.value) return 'A'
  if (props.message.role === 'user') return 'U'
  if (props.message.role === 'system') return 'S'
  return 'A'
})

const visibleParts = computed(() => props.message.parts)
const collaborationReport = computed(() => {
  const report = props.message.metadata?.collaboration_report
  return report && typeof report === 'object' ? report as Record<string, any> : null
})
const collaborationReportTitle = computed(() => {
  const packageId = String(collaborationReport.value?.assignee_package_id || '').trim()
  return packageId
    ? t('collaboration.workerReportWithAgent', { agent: packageId })
    : t('collaboration.workerReport')
})
const collaborationReportStatus = computed(() => {
  const status = String(collaborationReport.value?.status || '').trim()
  if (status === 'submitted') return t('collaboration.reportSubmitted')
  if (status === 'failed') return t('collaboration.reportFailed')
  if (status === 'cancelled') return t('collaboration.reportCancelled')
  if (status === 'blocked') return t('collaboration.reportBlocked')
  return status || t('collaboration.reportUpdated')
})

function formatTime(timestamp: string): string {
  const date = new Date(timestamp)
  const now = new Date()
  const diff = now.getTime() - date.getTime()

  // 小于 1 分钟
  if (diff < 60000) {
    return t('time.justNow')
  }

  // 小于 1 小时
  if (diff < 3600000) {
    const minutes = Math.floor(diff / 60000)
    return t('time.minutesAgo', { count: minutes })
  }

  // 今天
  if (date.toDateString() === now.toDateString()) {
    return date.toLocaleTimeString(locale.value, {
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  // 更早
  return date.toLocaleString(locale.value, {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function shortId(value: unknown): string {
  const text = String(value || '').trim()
  return text.length > 8 ? text.slice(0, 8) : text
}

function compactSummary(value: unknown): string {
  const text = String(value || '').replace(/\s+/g, ' ').trim()
  if (text.length <= 220) return text
  return `${text.slice(0, 220)}...`
}

</script>

<style scoped>
.message-item {
  display: flex;
  gap: var(--app-space-md);
  padding: var(--app-space-lg) var(--app-space-md);
  border-radius: var(--app-radius-lg);
  transition: background-color var(--app-transition-base), transform var(--app-transition-spring), box-shadow var(--app-transition-base);
  animation: app-fade-in-up 0.55s var(--app-transition-spring) both;
}

.message-item.role-assistant {
  background: var(--app-surface-elevated);
  border: none;
  box-shadow: var(--app-shadow-sm);
}

.message-item.streaming {
  position: relative;
  animation: app-fade-in-up 0.55s var(--app-transition-spring) both,
             message-pulse 3s ease-in-out infinite;
}

@keyframes message-pulse {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.005); }
}

.message-item.streaming::before {
  content: '';
  position: absolute;
  left: 0;
  top: 18px;
  bottom: 18px;
  width: 2px;
  background: var(--app-border-hover);
  border-radius: var(--app-radius-pill);
  opacity: 0.42;
  animation: app-pulse-soft 2.4s ease-in-out infinite;
}

.message-item.role-user {
  background-color: transparent;
}

.message-item:hover {
  background-color: var(--app-surface-hover);
  transform: translateX(2px);
}

.message-item.role-assistant:hover {
  box-shadow: var(--app-shadow-md);
  transform: translateX(4px) translateY(-1px);
}

.message-item + .message-item {
  margin-top: var(--app-space-md);
}

.message-avatar {
  flex-shrink: 0;
  padding-top: 2px;
  animation: app-pop-in 0.35s cubic-bezier(0.16, 1, 0.3, 1) both;
}

.message-content {
  flex: 1;
  min-width: 0;
}

.message-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--app-space-sm);
  margin-bottom: var(--app-space-sm);
}

.message-body {
  position: relative;
  font-size: var(--app-font-lg);
  line-height: var(--app-leading-relaxed);
}

.collaboration-report-card {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-xs);
  padding: var(--app-space-md);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  background: var(--app-surface-muted);
}

.collaboration-report-title {
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-xs);
  color: var(--app-text-strong);
  font-size: var(--app-font-md);
  font-weight: 600;
}

.collaboration-report-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--app-success);
}

.collaboration-report-meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--app-space-xs);
  color: var(--app-text-secondary);
  font-size: var(--app-font-sm);
}

.collaboration-report-meta span {
  padding: 2px 8px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-pill);
  background: var(--app-surface);
}

.collaboration-report-summary {
  color: var(--app-text);
  font-size: var(--app-font-md);
  line-height: var(--app-leading-relaxed);
}

.streaming-caret {
  display: inline-block;
  width: 2px;
  height: 18px;
  margin-left: 4px;
  vertical-align: text-bottom;
  background: var(--app-text);
  border-radius: 1px;
  animation: streaming-caret-blink 1.2s ease-in-out infinite;
}

@keyframes streaming-caret-blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}

.thinking-content {
  width: fit-content;
  min-width: 54px;
  height: 28px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  padding: 0 12px;
  border: 1px solid var(--app-border);
  border-radius: 999px;
  background: var(--app-surface-muted);
}

.thinking-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--app-text);
  animation: thinking-pulse 1.05s ease-in-out infinite;
}

.thinking-dot:nth-child(2) {
  animation-delay: 0.14s;
}

.thinking-dot:nth-child(3) {
  animation-delay: 0.28s;
}

@keyframes thinking-pulse {
  0%,
  80%,
  100% {
    opacity: 0.32;
    transform: translateY(0);
  }
  40% {
    opacity: 1;
    transform: translateY(-3px);
  }
}
</style>
