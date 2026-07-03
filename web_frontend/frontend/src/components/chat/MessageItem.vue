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

      <div ref="messageBodyRef" class="message-body">
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
import { computed, ref } from 'vue'
import type { CSSProperties } from 'vue'
import { NAvatar, NIcon, NText } from 'naive-ui'
import { Document, Link, Text } from '@vicons/ionicons5'
import { useI18n } from '@/composables/useI18n'
import { useMarkdownRenderer } from '@/composables/useMarkdownRenderer'
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

const { locale, t } = useI18n()
const messageBodyRef = ref<HTMLElement | null>(null)
const { renderMarkdown } = useMarkdownRenderer(messageBodyRef)

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
  return renderMarkdown(props.message.content, { streaming: props.streaming, surface: 'chat_message' })
})

const hasReasoning = computed(() => Boolean(props.message.reasoning?.content?.trim()))
const reasoningOpen = computed(() => hasReasoning.value)
const reasoningLabel = computed(() => (
  props.message.reasoning?.active
    ? t('roles.assistantReasoningActive')
    : t('roles.assistantReasoning')
))
const renderedReasoning = computed(() => {
  return renderMarkdown(props.message.reasoning?.content || '', {
    streaming: Boolean(props.message.reasoning?.active),
    surface: 'reasoning',
  })
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
  top: 12px;
  bottom: 12px;
  width: 4px;
  background: linear-gradient(
    180deg,
    transparent,
    var(--app-primary) 20%,
    var(--app-primary) 80%,
    transparent
  );
  background-size: 100% 200%;
  border-radius: var(--app-radius-pill);
  animation: glass-gradient-flow 2.5s ease-in-out infinite;
  box-shadow: 0 0 12px var(--app-primary);
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
