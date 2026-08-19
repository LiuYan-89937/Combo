<template>
  <div
    class="message-item"
    :class="[`role-${message.role}`, { streaming }]"
    :data-reference-label="`${roleLabel} · ${formatTime(message.timestamp)}`"
  >
    <template v-if="delegatedDelivery">
      <div class="delegated-delivery-message">
        <MessagePartRenderer
          v-for="part in visibleParts"
          :key="part.id"
          :part="part"
          :workspace-context="workspaceContext"
        />
      </div>
    </template>

    <template v-else>
    <div class="message-avatar" aria-hidden="true">
      <ComboFrameAnimation
        :character="message.role === 'user' ? 'lead' : 'companion'"
        action="idle"
        :size="message.role === 'user' ? 32 : 30"
        paused
      />
    </div>

    <div class="message-content">
      <div class="message-header">
        <span class="message-author" :class="{ 'combo-wordmark': message.role === 'assistant' }">{{ roleLabel }}</span>
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
          v-if="quoteable && message.role !== 'user'"
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
        <template v-for="block in displayBlocks" :key="block.id">
          <ToolTraceGroup
            v-if="block.kind === 'tools'"
            embedded
            :executions="block.executions"
            :timestamp="block.timestamp"
            :workspace-context="workspaceContext"
          />
          <template v-else>
            <MessagePartRenderer
              v-for="part in block.parts"
              :key="part.id"
              :part="part"
              :highlight-mentions="isGroupUserMessage"
              :mention-names="mentionNames"
              :workspace-context="workspaceContext"
            />
          </template>
        </template>

        <GitChangeCapsule
          v-if="message.role === 'assistant' && gitChanges?.files.length"
          :changes="gitChanges"
        />
      </div>
    </div>
    </template>

  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NButton, NIcon, NTag, NText } from 'naive-ui'
import { ReturnUpBackOutline } from '@/components/icons'
import { useI18n } from '@/composables/useI18n'
import MessagePartRenderer from './MessagePartRenderer.vue'
import ComboFrameAnimation from '@/components/brand/ComboFrameAnimation.vue'
import ToolTraceGroup from './ToolTraceGroup.vue'
import GitChangeCapsule from './GitChangeCapsule.vue'
import type { GitTurnChanges } from '@/api/git'
import type { ChatMessagePart, ToolExecutionMessagePart, TranscriptItem } from '@/types/protocol'
import { conversationVisibleMessageParts, conversationVisibleParts } from '@/utils/toolPresentation'
import type { WorkspaceRequestContext } from '@/api/resourceTypes'

const props = withDefaults(
  defineProps<{
    message: TranscriptItem
    streaming?: boolean
    quoteable?: boolean
    workspaceContext?: WorkspaceRequestContext | null
    messages?: TranscriptItem[]
    gitChanges?: GitTurnChanges | null
  }>(),
  {
    streaming: false,
    quoteable: false,
    workspaceContext: null,
    messages: () => [],
    gitChanges: null,
  }
)

defineEmits<{
  quote: [message: TranscriptItem]
}>()

const { locale, t } = useI18n()
const roleLabel = computed(() => {
  const displayName = String(props.message.metadata?.display_name || '').trim()
  if (props.message.role === 'assistant' && !props.message.metadata?.agent_group_speaker) return 'Combo'
  if (displayName) return displayName
  if (props.message.role === 'user') return t('roles.user')
  if (props.message.role === 'system') return t('roles.system')
  return t('roles.assistant')
})

const visibleParts = computed(() => conversationVisibleParts(props.message.parts))
type MessageDisplayBlock =
  | { kind: 'parts'; id: string; parts: ChatMessagePart[] }
  | { kind: 'tools'; id: string; executions: ToolExecutionMessagePart[]; timestamp: string }

const displayBlocks = computed<MessageDisplayBlock[]>(() => {
  const blocks: MessageDisplayBlock[] = []
  const sequence = props.messages.length ? props.messages : [props.message]
  let currentKind: 'parts' | 'tools' | null = null
  let currentParts: ChatMessagePart[] = []
  const flush = () => {
    if (!currentKind || currentParts.length === 0) return
    if (currentKind === 'parts') {
      blocks.push({
        kind: 'parts',
        id: `parts-${currentParts[0].id}`,
        parts: currentParts,
      })
    } else {
      const executions = currentParts.filter(
        (part): part is ToolExecutionMessagePart => part.type === 'tool_execution',
      )
      blocks.push({
        kind: 'tools',
        id: `tools-${executions[0].id}`,
        executions,
        timestamp: executions[0].createdAt || props.message.timestamp,
      })
    }
    currentParts = []
  }
  conversationVisibleMessageParts(sequence).forEach((part) => {
    const nextKind = part.type === 'tool_execution' ? 'tools' : 'parts'
    if (currentKind && currentKind !== nextKind) flush()
    currentKind = nextKind
    currentParts.push(part)
  })
  flush()
  return blocks
})
const delegatedDelivery = computed(() => (
  Boolean(props.message.metadata?.delegated_delivery)
  && visibleParts.value.some(part => part.type === 'delegated_delivery')
))
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

</script>

<style scoped>
.message-item {
  position: relative;
  display: flex;
  gap: 10px;
  padding: 10px 8px;
  border-radius: 12px;
  transition: background-color var(--app-transition-base);
}

.message-item:has(.delegated-delivery-message) { padding-block: var(--app-space-xs); }
.delegated-delivery-message { min-width: 0; }

.message-item.role-assistant {
  background: transparent;
  border: none;
  box-shadow: none;
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

.message-item.role-user {
  background-color: transparent;
  flex-direction: row-reverse;
  justify-content: flex-start;
}

.message-item:hover {
  background-color: color-mix(in srgb, var(--app-text) 2.5%, transparent);
}

.message-item.role-assistant:hover {
  box-shadow: none;
}

.message-item + .message-item {
  margin-top: 6px;
}

.message-avatar {
  display: grid;
  flex-shrink: 0;
  min-width: 34px;
  padding-top: 0;
  place-items: start center;
}

.message-content {
  flex: 1;
  min-width: 0;
}

.message-header {
  display: flex;
  align-items: baseline;
  justify-content: flex-start;
  gap: 7px;
  margin-bottom: 5px;
}

.message-author {
  color: var(--app-text);
  font-size: 13px;
  font-weight: 700;
  line-height: 1.2;
}

.combo-wordmark {
  font-family: 'Avenir Next', 'SF Pro Display', 'Arial Rounded MT Bold', sans-serif;
  font-size: 15px;
  font-weight: 780;
  letter-spacing: -.055em;
}

.role-user .message-content {
  flex: 0 1 auto;
  width: fit-content;
  max-width: min(82%, 920px);
  margin-left: auto;
}

.role-user .message-header {
  justify-content: flex-end;
}

.role-user .message-body {
  display: grid;
  justify-items: end;
}

.quote-button {
  margin-left: auto;
}

.message-body {
  position: relative;
  font-size: var(--app-font-lg);
  line-height: 1.6;
}

.role-user :deep(.message-image-card) {
  max-width: min(360px, 100%);
}

.role-user :deep(.message-image-card img) {
  max-height: 280px;
}

@media (max-width: 680px) {
  .message-item {
    padding-inline: var(--app-space-sm);
  }

  .role-user .message-content {
    max-width: calc(100% - 52px);
  }
}

</style>
