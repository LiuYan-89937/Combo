<template>
  <div
    class="message-item"
    :class="[`role-${message.role}`, { streaming }]"
    :data-reference-label="`${roleLabel} · ${formatTime(message.timestamp)}`"
  >
    <template v-if="runtimeErrorPart">
      <div class="runtime-error-message">
        <MessagePartRenderer :part="runtimeErrorPart" />
      </div>
    </template>

    <template v-else-if="delegatedDelivery">
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
        <!--
          回合级「工作区」摘要。工具调用是嵌在 AI 回合里的活动节点：回合进行中
          它们直接铺开，回合结束后整段工作折成这一行，回答留在下面。
        -->
        <button
          v-if="showWorkDigest"
          type="button"
          class="turn-work-digest"
          :title="workDigestTitle"
          :aria-expanded="!workCollapsed"
          :aria-label="t('tool.digest.workLabel')"
          @click="toggleWork"
        >
          <span class="digest-mark" aria-hidden="true"></span>
          <span class="digest-text">
            <template v-for="(segment, index) in workDigestSegments" :key="index">
              <span v-if="index > 0" class="digest-separator">·</span>
              <span :class="`digest-tone-${segment.tone}`">{{ segment.text }}</span>
            </template>
          </span>
          <span class="digest-chevron" aria-hidden="true">⌄</span>
        </button>

        <template v-for="block in displayBlocks" :key="block.id">
          <ToolTraceGroup
            v-if="block.kind === 'tools'"
            v-show="!workCollapsed"
            embedded
            :executions="block.executions"
            :timestamp="block.timestamp"
            :workspace-context="workspaceContext"
          />
          <MessageImageGallery
            v-else-if="block.kind === 'images'"
            :parts="block.parts"
            :workspace-context="workspaceContext"
          />
          <template v-else>
            <MessagePartRenderer
              v-for="part in block.parts"
              v-show="isPartVisible(part)"
              :key="part.id"
              :part="part"
              :streaming="streaming"
              :class="{ 'is-turn-answer': part.id === answerPartId }"
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
import { computed, ref } from 'vue'
import { NButton, NIcon, NTag, NText } from 'naive-ui'
import { ReturnUpBackOutline } from '@/components/icons'
import { useI18n } from '@/composables/useI18n'
import MessagePartRenderer from './MessagePartRenderer.vue'
import MessageImageGallery from './MessageImageGallery.vue'
import ComboFrameAnimation from '@/components/brand/ComboFrameAnimation.vue'
import ToolTraceGroup from './ToolTraceGroup.vue'
import GitChangeCapsule from './GitChangeCapsule.vue'
import type { GitTurnChanges } from '@/api/git'
import type { AttachmentMessagePart, ChatMessagePart, ToolExecutionMessagePart, TranscriptItem } from '@/types/protocol'
import { conversationVisibleMessageParts, conversationVisibleParts } from '@/utils/toolPresentation'
import { toolTraceSummary } from '@/utils/toolTraceSummary'
import { isImageResource } from '@/utils/workspaceResources'
import { formatClockTime, isToday, parseDate } from '@/utils/format'
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
const runtimeErrorPart = computed(() => {
  if (props.message.role !== 'system' || visibleParts.value.length !== 1) return null
  const part = visibleParts.value[0]
  return part.type === 'error' ? part : null
})
type MessageDisplayBlock =
  | { kind: 'parts'; id: string; parts: ChatMessagePart[] }
  | { kind: 'images'; id: string; parts: AttachmentMessagePart[] }
  | { kind: 'tools'; id: string; executions: ToolExecutionMessagePart[]; timestamp: string }

const displayBlocks = computed<MessageDisplayBlock[]>(() => {
  const blocks: MessageDisplayBlock[] = []
  const sequence = props.messages.length ? props.messages : [props.message]
  let currentKind: 'parts' | 'images' | 'tools' | null = null
  let currentParts: ChatMessagePart[] = []
  const flush = () => {
    if (!currentKind || currentParts.length === 0) return
    if (currentKind === 'parts') {
      blocks.push({
        kind: 'parts',
        id: `parts-${currentParts[0].id}`,
        parts: currentParts,
      })
    } else if (currentKind === 'images') {
      const images = currentParts.filter(
        (part): part is AttachmentMessagePart => part.type === 'attachment',
      )
      if (images.length > 0) {
        blocks.push({
          kind: 'images',
          id: `images-${images[0].id}`,
          parts: images,
        })
      }
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
    const nextKind = part.type === 'tool_execution'
      ? 'tools'
      : part.type === 'attachment' && isImageResource(part.attachment.name, part.attachment.mime_type)
        ? 'images'
        : 'parts'
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

// ---------------------------------------------------------------- AI 回合层级
//
// 一个 AI 回合 = 工作记录（进度说明 + 工具活动流）+ 最终回答。工具调用是嵌在
// 回合里的活动节点，不是独立的消息气泡：回合结束后整段工作折成一行摘要，
// 回答留在下面，层级靠「折叠」而不是靠给回答加装饰来形成。
const isAssistantTurn = computed(() => props.message.role === 'assistant')

const turnSequence = computed(() => (props.messages.length ? props.messages : [props.message]))
const turnParts = computed(() => conversationVisibleMessageParts(turnSequence.value))

const turnExecutions = computed<ToolExecutionMessagePart[]>(() => (
  turnParts.value.filter((part): part is ToolExecutionMessagePart => part.type === 'tool_execution')
))
const workSummary = computed(() => toolTraceSummary(turnExecutions.value))

/**
 * 「最终回答」= 回合里最后一个文本 part，并且它后面没有再发生工具调用。
 * 用位置判定而不是后端标记：流式过程中就已经成立，而且翻转只改样式、不搬 DOM。
 */
const answerPartId = computed(() => {
  if (!isAssistantTurn.value) return ''
  const parts = turnParts.value
  for (let index = parts.length - 1; index >= 0; index -= 1) {
    const part = parts[index]
    if (part.type === 'tool_execution') return ''
    if (part.type === 'text') return part.id
  }
  return ''
})

const workNoteCount = computed(() => (
  turnParts.value.filter(part => part.type === 'text' && part.id !== answerPartId.value).length
))

/** 用户手动开合过的状态；null 表示跟随默认（有失败就展开）。 */
const workOpenState = ref<boolean | null>(null)
const workCollapsed = computed(() => {
  if (!isAssistantTurn.value) return false
  if (props.streaming) return false
  if (turnExecutions.value.length === 0) return false
  const open = workOpenState.value ?? workSummary.value.failureCount > 0
  return !open
})

const workDigestSegments = computed<Array<{ text: string; tone: 'default' | 'failed' | 'running' }>>(() => {
  if (!isAssistantTurn.value || turnExecutions.value.length === 0) return []
  const summary = workSummary.value
  const segments: Array<{ text: string; tone: 'default' | 'failed' | 'running' }> = []
  // 失败与进行中放最前面：这一行会被省略号截断，不能把要立刻反应的状态藏在末尾。
  if (summary.failureCount > 0) {
    segments.push({ text: t('tool.digest.failed', { count: summary.failureCount }), tone: 'failed' })
  }
  if (summary.runningCount > 0) {
    segments.push({ text: t('tool.digest.running', { count: summary.runningCount }), tone: 'running' })
  }
  const categories: Array<[keyof typeof summary.byCategory, string]> = [
    ['read', 'tool.digest.read'],
    ['search', 'tool.digest.search'],
    ['process', 'tool.digest.process'],
    ['agent', 'tool.digest.agent'],
    ['knowledge', 'tool.digest.knowledge'],
    ['scheduler', 'tool.digest.scheduler'],
    ['extension', 'tool.digest.extension'],
    ['generic', 'tool.digest.other'],
  ]
  categories.forEach(([category, key]) => {
    const count = summary.byCategory[category] || 0
    if (count > 0) segments.push({ text: t(key as any, { count }), tone: 'default' })
  })
  // 写工具按实际改动的文件数报，多个编辑落在一个文件上时不会重复计数。
  const writeFiles = summary.changedFileCount || summary.byCategory.write || 0
  if (writeFiles > 0) {
    segments.splice(
      Math.min(2, segments.length),
      0,
      { text: t('tool.digest.write', { count: writeFiles }), tone: 'default' },
    )
  }
  if (workNoteCount.value > 0) {
    segments.push({ text: t('tool.digest.notes', { count: workNoteCount.value }), tone: 'default' })
  }
  return segments
})

const workDigestTitle = computed(() => workDigestSegments.value.map(segment => segment.text).join(' · '))
const showWorkDigest = computed(() => workDigestSegments.value.length > 0 && !props.streaming)

function toggleWork(): void {
  workOpenState.value = workCollapsed.value
}

/**
 * 折叠只收「工作记录」（进展说明 + 工具调用）。产物、附件、错误属于交付物，
 * 必须继续可见——否则收起工作区会把消息里的图片/文件一起藏掉，用户根本点不到。
 */
const WORK_ONLY_PART_TYPES = new Set(['text', 'reasoning', 'tool_call', 'tool_result', 'tool_execution', 'status'])

function isPartVisible(part: ChatMessagePart): boolean {
  if (!workCollapsed.value) return true
  if (part.id === answerPartId.value) return true
  return !WORK_ONLY_PART_TYPES.has(part.type)
}
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
  const date = parseDate(timestamp)
  if (!date) return timestamp
  const diff = Date.now() - date.getTime()

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
  if (isToday(date)) {
    return formatClockTime(date, locale.value)
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
  gap: 8px;
  padding: 6px 8px;
  border-radius: var(--app-radius-md);
  transition: background-color var(--app-transition-base);
}

.message-item:has(.delegated-delivery-message) { padding-block: var(--app-space-xs); }
.delegated-delivery-message { min-width: 0; }
.message-item:has(.runtime-error-message) { padding-block: var(--app-space-xs); }
.runtime-error-message { width: 100%; min-width: 0; }

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

:root[data-theme='dark'] .message-item:hover {
  background-color: color-mix(in srgb, var(--app-text) 2.5%, transparent);
}

.message-item.role-assistant:hover {
  box-shadow: none;
}

.message-item + .message-item {
  margin-top: 2px;
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
  margin-bottom: 3px;
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
  line-height: 1.55;
}

/* Attachments are fixed-size tiles, so the user bubble only constrains the row. */
/**
 * AI 回合层级：工作记录（进度说明 + 工具活动流）与最终回答。
 *
 * 层级主要靠「回合结束后整段工作折叠」形成，颜色和字号只是辅助：工作区里的
 * 说明是次级对比度，最终回答保持满对比度并大一号。这样工具调用读起来是回合内
 * 的活动节点，不会和回答抢注意力。
 */
.role-assistant :deep(.message-part:not(.is-turn-answer)) .markdown-content {
  color: var(--app-text-secondary);
}

.role-assistant :deep(.message-part.is-turn-answer) .markdown-content {
  color: var(--app-text);
  font-size: 15px;
}

.turn-work-digest {
  display: flex;
  width: 100%;
  align-items: center;
  gap: 8px;
  margin: 1px 0 3px;
  padding: 3px 2px;
  border: 0;
  background: transparent;
  color: var(--app-text-muted);
  font-family: inherit;
  font-size: var(--app-font-sm);
  line-height: 1.5;
  text-align: left;
  cursor: pointer;
}

.turn-work-digest:hover { color: var(--app-text-secondary); }

.digest-mark {
  width: 6px;
  height: 6px;
  flex: 0 0 6px;
  border-radius: 50%;
  background: currentColor;
  opacity: 0.6;
}

.digest-text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.digest-separator {
  margin: 0 4px;
  opacity: 0.6;
}

.digest-tone-failed { color: var(--app-diff-deletion); }

.digest-chevron {
  flex: 0 0 auto;
  margin-left: auto;
  font-size: 11px;
  line-height: 1;
  transition: transform var(--app-transition-fast);
}

.turn-work-digest[aria-expanded='false'] .digest-chevron {
  transform: rotate(-90deg);
}

/* Attachments are fixed-size tiles, so the user bubble only constrains the row. */
.role-user :deep(.message-image-gallery) {
  max-width: min(420px, 100%);
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
