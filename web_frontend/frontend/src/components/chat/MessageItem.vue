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
          v-if="message.role === 'assistant'"
          class="markdown-content"
          v-html="renderedContent"
        ></div>
        <div v-else class="plain-content">
          {{ message.content }}
        </div>

        <div v-if="streaming" class="streaming-indicator">
          <n-spin :size="14" />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { CSSProperties } from 'vue'
import { NAvatar, NText, NSpin } from 'naive-ui'
import { useMarkdown } from '@/composables/useMarkdown'
import type { TranscriptItem } from '@/types/protocol'

const props = withDefaults(
  defineProps<{
    message: TranscriptItem
    streaming?: boolean
  }>(),
  {
    streaming: false,
  }
)

const { renderMarkdown } = useMarkdown()

const roleLabel = computed(() => {
  if (props.message.role === 'user') return '你'
  if (props.message.role === 'system') return '系统'
  return 'Assistant'
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
  return renderMarkdown(props.message.content)
})

function formatTime(timestamp: string): string {
  const date = new Date(timestamp)
  const now = new Date()
  const diff = now.getTime() - date.getTime()

  // 小于 1 分钟
  if (diff < 60000) {
    return '刚刚'
  }

  // 小于 1 小时
  if (diff < 3600000) {
    const minutes = Math.floor(diff / 60000)
    return `${minutes} 分钟前`
  }

  // 今天
  if (date.toDateString() === now.toDateString()) {
    return date.toLocaleTimeString('zh-CN', {
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  // 更早
  return date.toLocaleString('zh-CN', {
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

.streaming-indicator {
  display: inline-flex;
  margin-left: 8px;
  vertical-align: middle;
}
</style>

<style>
/* Markdown 样式 */
.markdown-content {
  line-height: 1.6;
  color: var(--n-text-color);
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
  margin-bottom: 16px;
}

.markdown-content code {
  padding: 0.2em 0.4em;
  margin: 0;
  font-size: 85%;
  background-color: var(--n-color-embedded);
  border-radius: 6px;
  font-family: 'SF Mono', Monaco, 'Cascadia Code', 'Roboto Mono', monospace;
}

.markdown-content pre {
  padding: 16px;
  overflow: auto;
  font-size: 85%;
  line-height: 1.45;
  background-color: var(--n-color-embedded);
  border-radius: 6px;
  margin-bottom: 16px;
}

.markdown-content pre code {
  padding: 0;
  background-color: transparent;
  border: 0;
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
  border-collapse: collapse;
  width: 100%;
  margin-bottom: 16px;
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
