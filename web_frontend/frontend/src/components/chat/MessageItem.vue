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
          v-if="thinking"
          class="thinking-content"
          role="status"
          aria-live="polite"
          :aria-label="t('roles.assistantThinking')"
        >
          <span class="thinking-dot"></span>
          <span class="thinking-dot"></span>
          <span class="thinking-dot"></span>
        </div>
        <template v-else-if="message.role === 'assistant'">
          <details
            v-if="hasReasoning"
            class="reasoning-panel"
            :open="reasoningOpen"
          >
            <summary class="reasoning-summary">
              <span
                v-if="message.reasoning?.active"
                class="reasoning-live-dot"
                aria-hidden="true"
              ></span>
              <span>{{ reasoningLabel }}</span>
            </summary>
            <div
              class="markdown-content reasoning-markdown"
              v-html="renderedReasoning"
            ></div>
          </details>
          <div
            v-if="message.content.trim()"
            class="markdown-content"
            v-html="renderedContent"
          ></div>
        </template>
        <div v-else class="plain-content">
          {{ message.content }}
        </div>

        <div
          v-if="messageAttachments.length > 0"
          class="message-attachments"
          :aria-label="t('attachments.messageAttachments')"
        >
          <div
            v-for="(attachment, index) in messageAttachments"
            :key="`${attachment.kind}-${attachment.name}-${index}`"
            class="message-attachment-chip"
            :title="attachment.name"
          >
            <n-icon size="15" class="message-attachment-icon">
              <Document v-if="attachment.kind === 'file'" />
              <Link v-else-if="attachment.kind === 'url'" />
              <Text v-else />
            </n-icon>
            <span class="message-attachment-name">{{ attachment.name }}</span>
            <span class="message-attachment-kind">{{ attachmentKindLabel(attachment) }}</span>
          </div>
        </div>

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
import { NAvatar, NIcon, NText } from 'naive-ui'
import { Document, Link, Text } from '@vicons/ionicons5'
import { useI18n } from '@/composables/useI18n'
import { useMarkdown } from '@/composables/useMarkdown'
import type { TranscriptAttachmentView, TranscriptItem } from '@/types/protocol'

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

const { renderMarkdown } = useMarkdown()
const { locale, t } = useI18n()

const roleLabel = computed(() => {
  if (props.message.role === 'user') return t('roles.user')
  if (props.message.role === 'system') return t('roles.system')
  return t('roles.assistant')
})

const avatarStyle = computed<CSSProperties>(() => {
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
  if (props.message.role === 'user') return 'U'
  if (props.message.role === 'system') return 'S'
  return 'A'
})

const renderedContent = computed(() => {
  return renderMarkdown(props.message.content, { streaming: props.streaming })
})

const hasReasoning = computed(() => Boolean(props.message.reasoning?.content?.trim()))
const reasoningOpen = computed(() => Boolean(props.message.reasoning?.active))
const reasoningLabel = computed(() => (
  props.message.reasoning?.active
    ? t('roles.assistantReasoningActive')
    : t('roles.assistantReasoning')
))
const renderedReasoning = computed(() => {
  return renderMarkdown(props.message.reasoning?.content || '', { streaming: Boolean(props.message.reasoning?.active) })
})

const messageAttachments = computed(() => props.message.attachments || [])

function attachmentKindLabel(attachment: TranscriptAttachmentView): string {
  if (attachment.kind === 'url') return t('attachments.url')
  if (attachment.kind === 'text') return t('attachments.text')
  if (attachment.source_kind === 'workspace_file') return t('attachments.workspaceFile')
  return t('attachments.localFile')
}

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
</script>

<style scoped>
.message-item {
  display: flex;
  gap: var(--app-space-md);
  padding: var(--app-space-lg) var(--app-space-sm);
  border-radius: var(--app-radius-lg);
  transition: background-color var(--app-transition-base);
  animation: app-fade-in-up 0.32s cubic-bezier(0.16, 1, 0.3, 1) both;
}

.message-item.streaming {
  background-color: var(--app-surface-muted);
  position: relative;
}

.message-item.streaming::before {
  content: '';
  position: absolute;
  left: 0;
  top: 12px;
  bottom: 12px;
  width: 2px;
  background: var(--app-text);
  border-radius: var(--app-radius-pill);
  animation: app-pulse-soft 1.6s ease-in-out infinite;
}

.message-item.role-user {
  background-color: transparent;
}

.message-item:hover {
  background-color: var(--app-surface-hover);
}

.message-item + .message-item {
  margin-top: var(--app-space-xs);
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

.plain-content {
  white-space: pre-wrap;
  word-break: break-word;
}

.message-attachments {
  display: flex;
  flex-wrap: wrap;
  gap: var(--app-space-sm);
  margin-top: var(--app-space-md);
}

.message-attachment-chip {
  max-width: min(360px, 100%);
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-xs);
  padding: 4px var(--app-space-sm);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-pill);
  background: var(--app-surface-muted);
  color: var(--app-text);
  font-size: var(--app-font-sm);
  line-height: 1.4;
  transition: border-color var(--app-transition-fast), background-color var(--app-transition-fast);
}

.message-attachment-chip:hover {
  border-color: var(--app-border-hover);
  background: var(--app-surface-pressed);
}

.message-attachment-icon {
  flex: 0 0 auto;
}

.message-attachment-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.message-attachment-kind {
  flex: 0 0 auto;
  color: var(--app-text-muted);
  font-size: var(--app-font-xs);
}

.streaming-caret {
  display: inline-block;
  width: 8px;
  height: 16px;
  margin-left: 3px;
  vertical-align: text-bottom;
  background: var(--app-text);
  border-radius: 1px;
  animation: streaming-caret-blink 1s steps(2, start) infinite;
}

@keyframes streaming-caret-blink {
  0%, 50% { opacity: 1; }
  51%, 100% { opacity: 0; }
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

.reasoning-panel {
  margin-bottom: var(--app-space-md);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  background: var(--app-surface-muted);
  overflow: hidden;
}

.reasoning-summary {
  min-height: 34px;
  display: flex;
  align-items: center;
  gap: var(--app-space-xs);
  padding: 6px 10px;
  color: var(--app-text-secondary);
  font-size: var(--app-font-sm);
  cursor: pointer;
  user-select: none;
}

.reasoning-summary::-webkit-details-marker {
  display: none;
}

.reasoning-summary::before {
  content: '';
  width: 7px;
  height: 7px;
  border-right: 1.5px solid currentColor;
  border-bottom: 1.5px solid currentColor;
  transform: rotate(-45deg);
  transition: transform var(--app-transition-fast);
}

.reasoning-panel[open] .reasoning-summary::before {
  transform: rotate(45deg);
}

.reasoning-live-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--app-text);
  animation: app-pulse-soft 1.2s ease-in-out infinite;
}

.reasoning-markdown {
  max-height: 320px;
  padding: 0 12px 12px;
  color: var(--app-text-secondary);
  font-size: var(--app-font-sm);
  line-height: var(--app-leading-relaxed);
  overflow: auto;
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

<style>
/* Markdown 样式 */
.markdown-content {
  max-width: 100%;
  line-height: var(--app-leading-relaxed);
  color: var(--app-text);
  overflow-wrap: anywhere;
}

.markdown-content > :first-child {
  margin-top: 0;
}

.markdown-content > :last-child {
  margin-bottom: 0;
}

.markdown-content h1,
.markdown-content h2,
.markdown-content h3,
.markdown-content h4,
.markdown-content h5,
.markdown-content h6 {
  margin-top: 24px;
  margin-bottom: 12px;
  font-weight: 600;
  line-height: var(--app-leading-tight);
  color: var(--app-text-strong);
  letter-spacing: -0.01em;
}

.markdown-content h1 {
  font-size: 1.75em;
  border-bottom: 1px solid var(--app-divider);
  padding-bottom: 0.3em;
}

.markdown-content h2 {
  font-size: 1.4em;
  border-bottom: 1px solid var(--app-divider);
  padding-bottom: 0.3em;
}

.markdown-content h3 { font-size: 1.2em; }
.markdown-content h4 { font-size: 1.05em; }

.markdown-content p {
  margin: 0 0 14px;
}

.markdown-content code {
  padding: 0.15em 0.4em;
  margin: 0;
  font-size: 88%;
  background-color: var(--app-code-background);
  border: 1px solid var(--app-code-border);
  border-radius: var(--app-radius-sm);
  font-family: 'SF Mono', Monaco, 'Cascadia Code', 'Roboto Mono', monospace;
  word-break: break-word;
}

.markdown-content pre {
  max-width: 100%;
  padding: 14px 16px;
  overflow: auto;
  font-size: 88%;
  line-height: 1.55;
  background-color: var(--app-code-background);
  border: 1px solid var(--app-code-border);
  border-radius: var(--app-radius-md);
  margin-bottom: 16px;
  white-space: pre;
}

.markdown-content pre code {
  padding: 0;
  background-color: transparent;
  border: 0;
  white-space: inherit;
  word-break: normal;
}

.markdown-content ul,
.markdown-content ol {
  padding-left: 1.75em;
  margin-bottom: 14px;
}

.markdown-content li {
  margin-bottom: 4px;
}

.markdown-content blockquote {
  margin: 0 0 14px 0;
  padding: 4px 12px;
  color: var(--app-text-secondary);
  border-left: 3px solid var(--app-border-hover);
  background: var(--app-surface-muted);
  border-radius: 0 var(--app-radius-md) var(--app-radius-md) 0;
}

.markdown-content table {
  display: block;
  max-width: 100%;
  overflow-x: auto;
  border-collapse: collapse;
  width: 100%;
  margin-bottom: 14px;
  border-radius: var(--app-radius-md);
}

.markdown-content hr {
  margin: 18px 0;
  border: 0;
  border-top: 1px solid var(--app-divider);
}

.markdown-content table th,
.markdown-content table td {
  padding: 8px 13px;
  border: 1px solid var(--app-border);
}

.markdown-content table th {
  font-weight: 600;
  background-color: var(--app-surface-muted);
  color: var(--app-text-strong);
}

.markdown-content a {
  color: var(--app-info);
  text-decoration: none;
  border-bottom: 1px solid transparent;
  transition: border-color var(--app-transition-fast);
}

.markdown-content a:hover {
  border-bottom-color: currentColor;
}

.markdown-content img {
  max-width: 100%;
  height: auto;
  border-radius: var(--app-radius-md);
}
</style>
