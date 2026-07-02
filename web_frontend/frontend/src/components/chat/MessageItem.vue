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
        <div
          v-else-if="message.role === 'assistant'"
          class="markdown-content"
          v-html="renderedContent"
        ></div>
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

        <div v-if="streaming && !thinking" class="streaming-indicator">
          <n-spin :size="14" />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { CSSProperties } from 'vue'
import { NAvatar, NIcon, NText, NSpin } from 'naive-ui'
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
      background: '#ffffff',
      color: '#111111',
      border: '1px solid #111111',
    }
  }
  return {
    background: '#111111',
    color: '#ffffff',
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
  gap: 12px;
  padding: 16px;
  transition: background-color 0.2s;
}

.message-item.streaming {
  background-color: var(--n-color-embedded);
}

.message-item:hover {
  background-color: var(--n-color-hover);
}

.message-avatar {
  flex-shrink: 0;
}

.message-content {
  flex: 1;
  min-width: 0;
}

.message-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.message-body {
  position: relative;
}

.plain-content {
  white-space: pre-wrap;
  word-break: break-word;
}

.message-attachments {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}

.message-attachment-chip {
  max-width: min(360px, 100%);
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 8px;
  border: 1px solid var(--n-border-color);
  border-radius: 6px;
  background: var(--n-color);
  color: var(--n-text-color);
  font-size: 12px;
  line-height: 1.2;
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
  color: var(--n-text-color-3);
}

.streaming-indicator {
  display: inline-flex;
  margin-left: 8px;
  vertical-align: middle;
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
  border: 1px solid #111111;
  border-radius: 6px;
  background: #ffffff;
}

.thinking-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #111111;
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

<style>
/* Markdown 样式 */
.markdown-content {
  max-width: 100%;
  line-height: 1.65;
  color: var(--n-text-color);
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
  margin-bottom: 16px;
  font-weight: 600;
  line-height: 1.25;
}

.markdown-content h1 {
  font-size: 2em;
  border-bottom: 1px solid var(--n-border-color);
  padding-bottom: 0.3em;
}

.markdown-content h2 {
  font-size: 1.5em;
  border-bottom: 1px solid var(--n-border-color);
  padding-bottom: 0.3em;
}

.markdown-content p {
  margin: 0 0 14px;
}

.markdown-content code {
  padding: 0.2em 0.4em;
  margin: 0;
  font-size: 85%;
  background-color: var(--n-color-embedded);
  border-radius: 6px;
  font-family: 'SF Mono', Monaco, 'Cascadia Code', 'Roboto Mono', monospace;
  word-break: break-word;
}

.markdown-content pre {
  max-width: 100%;
  padding: 16px;
  overflow: auto;
  font-size: 85%;
  line-height: 1.45;
  background-color: var(--n-color-embedded);
  border-radius: 6px;
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
  padding-left: 2em;
  margin-bottom: 16px;
}

.markdown-content li {
  margin-bottom: 4px;
}

.markdown-content blockquote {
  margin: 0 0 16px 0;
  padding: 0 1em;
  color: var(--n-text-color-2);
  border-left: 0.25em solid var(--n-border-color);
}

.markdown-content table {
  display: block;
  max-width: 100%;
  overflow-x: auto;
  border-collapse: collapse;
  width: 100%;
  margin-bottom: 16px;
}

.markdown-content hr {
  margin: 18px 0;
  border: 0;
  border-top: 1px solid var(--n-border-color);
}

.markdown-content table th,
.markdown-content table td {
  padding: 6px 13px;
  border: 1px solid var(--n-border-color);
}

.markdown-content table th {
  font-weight: 600;
  background-color: var(--n-color-embedded);
}

.markdown-content a {
  color: var(--n-primary-color);
  text-decoration: none;
}

.markdown-content a:hover {
  text-decoration: underline;
}

.markdown-content img {
  max-width: 100%;
  height: auto;
}
</style>
