<template>
  <div
    class="message-item"
    :class="[`role-${message.role}`, { streaming, thinking }]"
    :data-reference-label="`${roleLabel} · ${formatTime(message.timestamp)}`"
  >
    <template v-if="thinking">
      <div
        class="thinking-content"
        role="status"
        aria-live="polite"
        :aria-label="message.content || t('roles.assistantThinking')"
      >
        <ComboFrameAnimation
          character="lead"
          action="running"
          :size="22"
        />
        <span class="thinking-label">{{ message.content || t('roles.assistantThinking') }}</span>
      </div>
    </template>

    <template v-else>
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
        <n-tag
          v-if="dispatchStatusLabel"
          :type="dispatchStatusType"
          size="tiny"
          :bordered="false"
        >
          {{ dispatchStatusLabel }}
        </n-tag>
        <n-button
          v-if="quoteable"
          class="quote-button"
          quaternary
          circle
          size="tiny"
          title="引用"
          @click="$emit('quote', message)"
        >
          <template #icon><n-icon><ReturnUpBackOutline /></n-icon></template>
        </n-button>
      </div>

      <div class="message-body">
        <MessagePartRenderer
          v-for="part in visibleParts"
          :key="part.id"
          :part="part"
          :streaming="streaming"
          :highlight-mentions="isGroupUserMessage"
          :mention-names="mentionNames"
          :workspace-context="workspaceContext"
        />

        <ComboFrameAnimation
          v-if="streaming && !thinking"
          class="streaming-running-note"
          character="lead"
          action="running"
          :size="25"
        />
      </div>
    </div>
    </template>

  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { CSSProperties } from 'vue'
import { NAvatar, NButton, NIcon, NTag, NText } from 'naive-ui'
import { ReturnUpBackOutline } from '@/components/icons'
import { useI18n } from '@/composables/useI18n'
import MessagePartRenderer from './MessagePartRenderer.vue'
import ComboFrameAnimation from '@/components/brand/ComboFrameAnimation.vue'
import type { TranscriptItem } from '@/types/protocol'
import { conversationVisibleParts } from '@/utils/toolPresentation'
import type { WorkspaceRequestContext } from '@/api/resourceTypes'

const props = withDefaults(
  defineProps<{
    message: TranscriptItem
    streaming?: boolean
    thinking?: boolean
    quoteable?: boolean
    workspaceContext?: WorkspaceRequestContext | null
  }>(),
  {
    streaming: false,
    thinking: false,
    quoteable: false,
    workspaceContext: null,
  }
)

defineEmits<{
  quote: [message: TranscriptItem]
}>()

const { locale, t } = useI18n()
const roleLabel = computed(() => {
  const displayName = String(props.message.metadata?.display_name || '').trim()
  if (displayName) return displayName
  if (props.message.role === 'user') return t('roles.user')
  if (props.message.role === 'system') return t('roles.system')
  return t('roles.assistant')
})

const avatarStyle = computed<CSSProperties>(() => {
  if (props.message.role === 'assistant') {
    if (Boolean(props.message.metadata?.agent_group_speaker)) {
      return groupAgentAvatarStyle(props.message.metadata)
    }
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
  const avatarLabel = String(props.message.metadata?.avatar_label || '').trim()
  if (avatarLabel) return avatarLabel.slice(0, 2)
  if (props.message.role === 'user') return 'U'
  if (props.message.role === 'system') return 'S'
  return 'A'
})

const visibleParts = computed(() => conversationVisibleParts(props.message.parts))
const isGroupUserMessage = computed(() => (
  props.message.role === 'user' && Boolean(props.message.metadata?.agent_group_message)
))
const mentionNames = computed(() => {
  const value = props.message.metadata?.mention_names
  return Array.isArray(value) ? value.map(item => String(item)).filter(Boolean) : []
})
const dispatchStatusLabel = computed(() => {
  if (props.message.role !== 'user') return ''
  const state = String(props.message.metadata?.dispatch_state || '')
  if (state === 'queued') {
    const position = Number(props.message.metadata?.queue_position || 0)
    return position > 0
      ? t('chat.messageQueuedAt', { position })
      : t('chat.messageQueued')
  }
  if (state === 'running') return t('chat.messageRunning')
  return ''
})
const dispatchStatusType = computed(() => (
  props.message.metadata?.dispatch_state === 'queued' ? 'warning' : 'info'
))

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

function groupAgentAvatarStyle(metadata: Record<string, unknown>): CSSProperties {
  void metadata
  return {
    background: 'var(--app-text)',
    color: 'var(--app-surface)',
    border: '1px solid var(--app-text)',
  }
}

</script>

<style scoped>
.message-item {
  position: relative;
  display: flex;
  gap: var(--app-space-md);
  padding: var(--app-space-lg) var(--app-space-md);
  border-radius: var(--app-radius-lg);
  transition: background-color var(--app-transition-base), transform var(--app-transition-spring), box-shadow var(--app-transition-base);
}

.message-item.role-assistant {
  background: var(--app-surface-elevated);
  border: none;
  box-shadow: var(--app-shadow-sm);
}

.message-item.streaming {
  position: relative;
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

.message-item.thinking {
  width: fit-content;
  max-width: 100%;
  padding: 2px var(--app-space-md);
  background: transparent;
  border: 0;
  box-shadow: none;
}

.message-item.thinking::before {
  display: none;
}

.message-item.thinking:hover {
  background: transparent;
  box-shadow: none;
  transform: none;
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

.quote-button {
  margin-left: auto;
}

.message-body {
  position: relative;
  font-size: var(--app-font-lg);
  line-height: var(--app-leading-relaxed);
}

.streaming-running-note {
  display: inline-grid;
  margin-left: 5px;
  vertical-align: text-bottom;
}

.thinking-content {
  width: fit-content;
  min-height: 24px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 0;
  border: 0;
  background: transparent;
}

.thinking-label {
  overflow: hidden;
  max-width: min(72vw, 720px);
  color: var(--app-text-tertiary);
  font-size: 12px;
  line-height: 18px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

</style>
