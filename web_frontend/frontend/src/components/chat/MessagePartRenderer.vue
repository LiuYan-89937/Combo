<template>
  <div ref="rootRef" class="message-part" :class="[`part-${part.type}`, { streaming: isStreaming, 'reasoning-live': isReasoningLive }]">
    <details
      v-if="part.type === 'reasoning'"
      class="reasoning-panel"
      :open="reasoningExpanded"
      @toggle="handleReasoningToggle"
    >
      <summary class="reasoning-summary">
        <span class="summary-icon" aria-hidden="true">
          <n-icon :size="18"><BulbOutline /></n-icon>
        </span>
        <span class="summary-left">
          <span class="summary-title">{{ isReasoningLive ? t('roles.assistantReasoningActive') : t('roles.assistantReasoning') }}</span>
        </span>
        <span class="summary-chevron" aria-hidden="true">⌄</span>
      </summary>
      <StreamingReasoningText v-if="isReasoningLive" :text="part.text" />
      <div v-else class="markdown-content reasoning-markdown" v-html="renderedReasoning"></div>
    </details>

    <template v-else-if="part.type === 'text' && part.format === 'markdown'">
      <!--
        Streaming renders each top-level block as its own element keyed by
        content, so blocks that are already finished keep their DOM (images are
        not reloaded, code blocks keep scroll and copy state) and only the block
        still being streamed is re-rendered. The finished message goes back to a
        single document render.
      -->
      <div v-if="streamingBlocks" class="markdown-content">
        <div
          v-for="block in streamingBlocks"
          :key="block.key"
          class="markdown-block"
          v-html="block.html"
        ></div>
      </div>
      <div v-else class="markdown-content" v-html="renderedText"></div>
    </template>

    <div v-else-if="part.type === 'text'" class="plain-content">
      {{ part.text }}
    </div>

    <MessageImageGallery
      v-else-if="part.type === 'attachment' && isImageAttachmentPart"
      :parts="imageAttachmentParts"
      :workspace-context="workspaceContext"
    />

    <button
      v-else-if="part.type === 'attachment'"
      type="button"
      class="message-attachment-chip"
      :class="{ openable: attachmentOpenable }"
      :title="attachmentOpenable ? t('attachments.openInWorkspace') : part.attachment.name"
      :disabled="!attachmentOpenable"
      @click="openAttachment"
    >
      <ResourceIcon
        :name="part.attachment.name"
        :mime-type="part.attachment.mime_type"
        :kind="part.attachment.kind"
        :size="18"
        class="message-attachment-icon"
      />
      <span class="message-attachment-name">{{ part.attachment.name }}</span>
      <span class="message-attachment-kind">{{ attachmentKindLabel(part.attachment) }}</span>
    </button>

    <details
      v-else-if="part.type === 'tool_call' || part.type === 'tool_result'"
      class="inline-tool-part"
      :class="[`tool-state-${toolState}`]"
      :open="toolExpanded"
      @toggle="handleToolToggle"
    >
      <summary class="inline-tool-summary">
        <span class="tool-summary-main">
          <span class="tool-status-dot" aria-hidden="true"></span>
          <span class="tool-summary-copy">
            <span class="tool-kind">{{ toolKindLabel }}</span>
            <strong class="tool-name">{{ toolName }}</strong>
          </span>
        </span>
        <span class="tool-summary-side">
          <span class="tool-status-pill">{{ toolStatusLabel }}</span>
          <span class="summary-chevron" aria-hidden="true">⌄</span>
        </span>
      </summary>
      <div v-if="toolPayload" class="tool-detail">
        <div class="tool-detail-label">{{ toolDetailLabel }}</div>
        <pre>{{ toolPayload }}</pre>
      </div>
      <div v-else class="tool-empty">{{ t('tool.noPayload') }}</div>
    </details>

    <ToolExecutionCard
      v-else-if="part.type === 'tool_execution'"
      :part="part"
      :workspace-context="workspaceContext"
    />

    <RuntimeErrorCard
      v-else-if="part.type === 'error'"
      :part="part"
    />

    <a
      v-else-if="part.type === 'artifact' && artifactImageUrl"
      class="message-image-card"
      :href="artifactImageUrl"
      target="_blank"
      rel="noopener noreferrer"
      :title="t('attachments.viewImage')"
      @click="handleArtifactImageClick"
    >
      <img :src="artifactImageUrl" :alt="part.name" />
      <span>{{ part.name }}</span>
    </a>

    <a
      v-else-if="part.type === 'artifact'"
      class="artifact-part"
      :href="artifactFileUrl || undefined"
      :target="artifactFileUrl ? '_blank' : undefined"
      :rel="artifactFileUrl ? 'noopener noreferrer' : undefined"
      @click="preventUnavailableArtifact"
    >
      <ResourceIcon :name="part.name" :mime-type="part.mimeType" :size="24" />
      <span class="artifact-copy">
        <strong>{{ part.name }}</strong>
        <small v-if="artifactMeta">{{ artifactMeta }}</small>
      </span>
    </a>

    <div v-else-if="part.type === 'status'" class="status-part">
      {{ part.message }}
    </div>

    <button
      v-else-if="part.type === 'delegated_delivery'"
      type="button"
      class="delegated-delivery-capsule"
      @click="reopenDelegatedTask"
    >
      <span class="delegated-delivery-dot" :class="`status-${part.terminalStatus}`" aria-hidden="true"></span>
      <strong>{{ part.taskName || t('backgroundTask.memberFallback') }}</strong>
      <span>{{ delegatedDeliveryLabel }}</span>
      <span class="delegated-delivery-chevron" aria-hidden="true">›</span>
    </button>

    <!-- Markdown body images open in the same viewer as attachment images. -->
    <ImageLightbox
      v-model:open="imageViewerOpen"
      v-model:index="imageViewerIndex"
      :images="imageViewerImages"
      :workspace-context="workspaceContext"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { NIcon } from 'naive-ui'
import { BulbOutline } from '@/components/icons'
import ResourceIcon from '@/components/common/ResourceIcon.vue'
import MessageImageGallery from '@/components/chat/MessageImageGallery.vue'
import ImageLightbox from '@/components/chat/ImageLightbox.vue'
import ToolExecutionCard from '@/components/chat/ToolExecutionCard.vue'
import RuntimeErrorCard from '@/components/chat/RuntimeErrorCard.vue'
import StreamingReasoningText from '@/components/chat/StreamingReasoningText.vue'
import { useI18n } from '@/composables/useI18n'
import { useAutoExpandedDetails } from '@/composables/useAutoExpandedDetails'
import { useImageViewer } from '@/composables/useImageViewer'
import { useMarkdownRenderer } from '@/composables/useMarkdownRenderer'
import type { MarkdownImageClickEvent } from '@/rendering/markdown/dom'
import { useWorkspaceFileOpener } from '@/composables/useWorkspaceFileOpener'
import { useWorkspaceResourceUrls } from '@/composables/useWorkspaceResourceUrls'
import type { AttachmentMessagePart, ChatMessagePart, TranscriptAttachmentView } from '@/types/protocol'
import type { WorkspaceRequestContext } from '@/api/resourceTypes'
import { toolPresentation } from '@/utils/toolPresentation'
import { isImageResource, workspaceFileReference, workspaceImageSources } from '@/utils/workspaceResources'
import { formatBytes } from '@/utils/format'

const props = defineProps<{
  part: ChatMessagePart
  streaming?: boolean
  highlightMentions?: boolean
  mentionNames?: string[]
  workspaceContext?: WorkspaceRequestContext | null
}>()

const { t } = useI18n()
const { openWorkspaceFile } = useWorkspaceFileOpener()
const rootRef = ref<HTMLElement | null>(null)
// 正文图片和 artifact 图片卡共用同一个查看器实例。
const {
  open: imageViewerOpen,
  index: imageViewerIndex,
  images: imageViewerImages,
  showImage,
} = useImageViewer()

/**
 * Markdown 正文图片只有解析后的 URL（没有工作区路径或上传 id），所以查看器
 * 里「用系统查看器打开」按无 path 判定为禁用，而不是报错。
 */
function handleMarkdownImageClick(event: MarkdownImageClickEvent): void {
  const name = (alt: string) => alt || t('attachments.imagePreview')
  showImage(
    { url: event.src, name: name(event.alt) },
    event.images.map(image => ({ url: image.src, name: name(image.alt) })),
  )
}

/**
 * artifact 图片卡以前是 `<a target="_blank">`，点开只会跳新标签、进不了我们的
 * 放大链路。现在左键点击走查看器；带修饰键或中键仍保留「开原始链接」这条退路。
 */
function handleArtifactImageClick(event: MouseEvent): void {
  if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
  if (props.part.type !== 'artifact') return
  const reference = props.part.path ? workspaceFileReference(props.part.path) : null
  const opened = showImage({
    url: artifactImageUrl.value,
    name: props.part.name,
    path: reference?.path ?? null,
    scope: reference?.scope ?? null,
  })
  if (opened) event.preventDefault()
}

const { renderMarkdown, renderStreamingBlocks } = useMarkdownRenderer(rootRef, {
  onImageClick: handleMarkdownImageClick,
})
const workspaceContext = computed(() => props.workspaceContext)
const protectedResourceSources = computed(() => {
  if (props.part.type === 'text' || props.part.type === 'reasoning') {
    return workspaceImageSources(props.part.text)
  }
  if (props.part.type === 'attachment') return props.part.attachment.path ? [props.part.attachment.path] : []
  if (props.part.type === 'artifact') return props.part.path ? [props.part.path] : []
  return []
})
const protectedResources = useWorkspaceResourceUrls(protectedResourceSources, workspaceContext)
const isImageAttachmentPart = computed(() => (
  props.part.type === 'attachment'
  && isImageResource(props.part.attachment.name, props.part.attachment.mime_type)
))
// Uploaded images render through the gallery so several images in one turn keep
// a regular grid instead of stacking at their natural sizes.
const imageAttachmentParts = computed<AttachmentMessagePart[]>(() => (
  props.part.type === 'attachment' && isImageAttachmentPart.value ? [props.part] : []
))

const isStreaming = computed(() => props.streaming || props.part.status === 'streaming')
/**
 * 思考条目「正在进行」的判定：必须看整条消息是否还在流式，而不只是 part 状态——
 * 回合结束后 part 仍可能留着 `status: 'streaming'`，那样思考行会一直停在进行态。
 */
const isReasoningLive = computed(() => props.part.type === 'reasoning' && props.streaming && isStreaming.value)
const streamingBlocks = computed(() => (
  props.part.type === 'text' && props.part.format === 'markdown' && isStreaming.value
    ? renderStreamingBlocks(markdownWithMentions(props.part.text), {
        streaming: true,
        surface: 'chat_message',
        resolveImageUrl: resolveMessageImageUrl,
      })
    : null
))
const renderedText = computed(() => (
  props.part.type === 'text' && props.part.format === 'markdown' && !streamingBlocks.value
    ? renderMarkdown(markdownWithMentions(props.part.text), {
        streaming: isStreaming.value,
        surface: 'chat_message',
        resolveImageUrl: resolveMessageImageUrl,
      })
    : ''
))
const renderedReasoning = computed(() => (
  props.part.type === 'reasoning' && !isReasoningLive.value
    ? renderMarkdown(props.part.text, {
        streaming: isReasoningLive.value,
        surface: 'reasoning',
        resolveImageUrl: resolveMessageImageUrl,
      })
    : ''
))
const attachmentOpenable = computed(() => (
  props.part.type === 'attachment'
  && Boolean(props.part.attachment.path && props.workspaceContext)
))
const artifactImageUrl = computed(() => {
  if (props.part.type !== 'artifact' || !props.part.path) return ''
  if (!isImageResource(props.part.path, props.part.mimeType)) return ''
  return resolveMessageImageUrl(props.part.path) || ''
})
const artifactFileUrl = computed(() => {
  if (props.part.type !== 'artifact' || !props.part.path) return ''
  return resolveMessageImageUrl(props.part.path) || ''
})
const artifactMeta = computed(() => {
  if (props.part.type !== 'artifact') return ''
  return [
    props.part.mimeType,
    typeof props.part.sizeBytes === 'number' ? formatBytes(props.part.sizeBytes) : null,
  ].filter(Boolean).join(' · ')
})
const delegatedDeliveryLabel = computed(() => {
  if (props.part.type !== 'delegated_delivery') return ''
  if (props.part.terminalStatus === 'result') return t('backgroundTask.delivery.completed')
  if (props.part.terminalStatus === 'failed') return t('backgroundTask.delivery.failed')
  return t('backgroundTask.delivery.cancelled')
})
const toolName = computed(() => {
  if (props.part.type !== 'tool_call' && props.part.type !== 'tool_result') return ''
  const rawName = String(props.part.toolName || '').trim()
  if (!rawName) return t('tool.call')
  const argumentsValue = props.part.type === 'tool_call' ? props.part.arguments : {}
  const presentation = toolPresentation(rawName, argumentsValue)
  return presentation.labelKey ? t(presentation.labelKey as any) : rawName
})

function reopenDelegatedTask() {
  if (props.part.type !== 'delegated_delivery') return
  window.dispatchEvent(new CustomEvent('combo:reopen-background-task', {
    detail: { task_id: props.part.taskId },
  }))
}
const toolKindLabel = computed(() => (
  props.part.type === 'tool_result' ? t('tool.result') : t('tool.call')
))
const toolState = computed(() => {
  const status = props.part.status || ''
  if (status === 'cancelled') return 'cancelled'
  if (status === 'failed') return 'failed'
  if (status === 'awaiting_approval') return 'approval'
  if (status === 'running' || status === 'streaming' || status === 'requested') return 'running'
  return 'completed'
})
const isToolActive = computed(() => toolState.value === 'running' || toolState.value === 'approval')

// Reasoning and inline tool blocks behave like the transcript's tool groups:
// they open while active and mount their body only once expanded. Liveness uses
// the message-level streaming flag so a lingering part status cannot keep the
// row open after the turn is over.
const { expanded: reasoningExpanded, handleToggle: handleReasoningToggle } = useAutoExpandedDetails(isReasoningLive)
const { expanded: toolExpanded, handleToggle: handleToolToggle } = useAutoExpandedDetails(
  computed(() => isToolActive.value || toolState.value === 'failed'),
)
const toolStatusLabel = computed(() => {
  const status = props.part.status || ''
  if (status === 'cancelled') return t('tool.status.cancelled')
  if (status === 'awaiting_approval') return t('tool.status.waitingApproval')
  if (status === 'requested') return t('tool.status.proposed')
  if (status === 'running' || status === 'streaming') return t('tool.status.started')
  if (status === 'failed') return t('tool.status.failed')
  if (status === 'stopped') return t('run.stopped')
  return t('tool.status.completed')
})
const toolDetailLabel = computed(() => {
  if (props.part.type === 'tool_call') return t('tool.arguments')
  if (props.part.type === 'tool_result' && props.part.error) return t('common.error')
  return t('tool.result')
})
const toolPayload = computed(() => {
  if (props.part.type === 'tool_call') return valueString(props.part.arguments)
  if (props.part.type === 'tool_result') return valueString(props.part.error || props.part.output)
  return ''
})

function attachmentKindLabel(attachment: TranscriptAttachmentView): string {
  if (attachment.kind === 'url') return t('attachments.url')
  if (attachment.kind === 'text') return t('attachments.text')
  if (attachment.source_kind === 'workspace_file') return t('attachments.workspaceFile')
  return t('attachments.localFile')
}

async function openAttachment(): Promise<void> {
  if (props.part.type !== 'attachment') return
  if (!props.part.attachment.path || !props.workspaceContext) return
  await openWorkspaceFile(
    props.part.attachment.path,
    props.workspaceContext,
    props.part.attachment.workspace_scope || 'workdir',
  )
}

function resolveMessageImageUrl(source: string): string | null {
  return protectedResources.resolve(source)
}

function preventUnavailableArtifact(event: MouseEvent) {
  if (!artifactFileUrl.value) event.preventDefault()
}

function valueString(value: unknown): string {
  if (value == null || value === '') return ''
  return typeof value === 'string' ? value : JSON.stringify(value, null, 2) || String(value)
}

function markdownWithMentions(content: string): string {
  if (!props.highlightMentions) return content
  const names = (props.mentionNames || [])
    .map(name => String(name).trim())
    .filter(Boolean)
    .sort((left, right) => right.length - left.length)
  if (!names.length) return content

  try {
    const alternatives = names.map(escapeRegExp).join('|')
    const mentionPattern = new RegExp(`@(${alternatives})(?=$|[\\s，。！？、,.!?;:])`, 'gu')
    return content.replace(mentionPattern, (_match, name: string) => `[@${name}](#agent-mention)`)
  } catch (error) {
    console.warn('Failed to create mention pattern:', error)
    return content
  }
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

</script>

<style scoped>
.delegated-delivery-capsule { width: fit-content; max-width: 100%; display: flex; align-items: center; gap: 8px; padding: 7px 10px; color: var(--app-text); background: var(--app-surface); border: 1px solid var(--app-border); border-radius: var(--app-radius-pill); cursor: pointer; transition: border-color .18s ease, transform .18s ease; }
.delegated-delivery-capsule:hover { transform: translateY(-1px); border-color: var(--app-text); }
.delegated-delivery-capsule strong { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; }
.delegated-delivery-capsule > span:not(.delegated-delivery-dot):not(.delegated-delivery-chevron) { color: var(--app-text-muted); font-size: 11px; }
.delegated-delivery-dot { width: 7px; height: 7px; flex: 0 0 auto; border-radius: 50%; background: var(--app-text); }
.delegated-delivery-dot.status-result { background: var(--app-success); }
.delegated-delivery-dot.status-failed { background: var(--app-error); }
.delegated-delivery-chevron { color: var(--app-text-muted); }

.message-part + .message-part {
  margin-top: 4px;
}

.message-part :deep(.markdown-content > :first-child) {
  margin-top: 0;
}

.message-part :deep(.markdown-content > :last-child) {
  margin-bottom: 0;
}

/* Markdown body images open the lightbox on click. */
.message-part :deep(.markdown-content img) {
  cursor: zoom-in;
}

.reasoning-panel {
  border: 0;
  border-radius: 0;
  background: transparent;
}

/*
 * 思考条目按「活动行」渲染：和工具活动行同一条轨道、同一列图标、同样的
 * 34px 行高与右侧箭头，展开态只显示一行摘要，默认折叠。
 */
.part-reasoning {
  position: relative;
  padding-left: 18px;
}

/* 与工具行 `.node-dot` 同规格、同一列，让两类条目在视觉上并列成一条流。 */
.part-reasoning::before {
  position: absolute;
  top: 14px;
  left: 5px;
  width: 8px;
  height: 8px;
  content: '';
  border: 2px solid var(--app-surface);
  border-radius: 50%;
  background: var(--app-text-muted);
  box-shadow: 0 0 0 1px var(--app-border-hover);
}

.reasoning-summary {
  display: flex;
  width: 100%;
  /* 34px 含上下 1px 边框，和工具活动行等高。 */
  min-height: 32px;
  align-items: center;
  justify-content: flex-start;
  gap: 8px;
  margin: 0;
  /* 3px + 26px 图标 + 3px + 上下 1px 边框 = 34px，与工具活动行等高。 */
  padding: 3px 6px;
  border: 1px solid transparent;
  border-radius: var(--app-radius-sm);
  color: var(--app-text-secondary);
  font-size: 12px;
  cursor: pointer;
  list-style: none;
  user-select: none;
  transition: background-color var(--app-transition-base), border-color var(--app-transition-base), color var(--app-transition-base);
}

/* 与工具行的 `.tool-icon-shell` 同宽同高，标题因此落在同一列。 */
.summary-icon {
  display: grid;
  flex: 0 0 26px;
  place-items: center;
  width: 26px;
  height: 26px;
  color: var(--app-text-subtle);
}

.reasoning-summary:hover {
  border-color: var(--app-border);
  background: var(--app-surface-muted);
  color: var(--app-text-secondary);
}

.reasoning-panel[open] > .reasoning-summary {
  border-color: color-mix(in srgb, var(--app-info) 24%, var(--app-border));
  background: color-mix(in srgb, var(--app-info) 6%, var(--app-surface-muted));
  color: var(--app-text-secondary);
}

.reasoning-summary::-webkit-details-marker { display: none; }

.summary-left,
.tool-summary-main,
.tool-summary-side {
  display: inline-flex;
  align-items: center;
  min-width: 0;
}

.summary-left {
  flex: 1 1 auto;
  gap: var(--app-space-xs);
}

.summary-title {
  font-weight: 550;
  letter-spacing: -0.01em;
}

.summary-chevron {
  flex: 0 0 auto;
  color: var(--app-text-subtle);
  font-size: 13px;
  line-height: 1;
  transition: transform var(--app-transition-base), color var(--app-transition-base);
}

.reasoning-summary:hover .summary-chevron { color: var(--app-text-secondary); }

details[open] > summary .summary-chevron {
  transform: rotate(180deg);
}

.reasoning-markdown {
  max-block-size: min(42vh, 32rem);
  overflow: auto;
  overscroll-behavior: contain;
  padding: 2px 0 var(--app-space-sm) 12px;
  color: var(--app-text-muted);
}

/* 进行中的思考：活性信号放在轨道点上，和工具行的 running 点一致，标题列不会跳动。 */
.part-reasoning.reasoning-live::before {
  background: var(--app-info);
  animation: app-pulse-soft 1.4s ease-in-out infinite;
}

.plain-content {
  white-space: pre-wrap;
  word-break: break-word;
}

.message-part :deep(a[href="#agent-mention"]) {
  color: var(--app-info);
  font-weight: 600;
  text-decoration: none;
}

.message-attachment-chip {
  appearance: none;
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-xs);
  max-width: 100%;
  padding: 4px 8px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  background: var(--app-surface-muted);
  color: var(--app-text);
  font-size: 12px;
  text-align: left;
}

.message-attachment-chip.openable {
  cursor: pointer;
}

.message-attachment-chip.openable:hover {
  border-color: var(--app-primary);
  background: var(--app-surface-hover);
}

.message-image-card {
  appearance: none;
  padding: 0;
  border: 0;
  background: transparent;
  cursor: pointer;
  display: inline-grid;
  gap: var(--app-space-xs);
  max-width: min(600px, 100%);
  color: var(--app-text-muted);
  font-size: 12px;
  text-decoration: none;
  text-align: left;
}

.message-image-card img {
  display: block;
  max-width: 100%;
  max-height: 400px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
  box-shadow: var(--app-shadow-sm);
  object-fit: contain;
  cursor: zoom-in;
}

.message-image-card span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.message-attachment-icon {
  flex: 0 0 auto;
  color: var(--app-text-muted);
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
}

.inline-tool-part,
.artifact-part,
.status-part {
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  background: var(--app-surface-muted);
}

.artifact-part,
.status-part {
  padding: var(--app-space-sm) var(--app-space-md);
}

.artifact-part {
  display: inline-flex;
  max-width: 100%;
  align-items: center;
  gap: var(--app-space-sm);
  color: var(--app-text);
  text-decoration: none;
}

.artifact-copy {
  display: grid;
  min-width: 0;
}

.artifact-copy strong,
.artifact-copy small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.artifact-copy small {
  color: var(--app-text-muted);
}

.inline-tool-part {
  overflow: hidden;
  border-color: color-mix(in srgb, var(--app-info) 28%, var(--app-border));
  background: color-mix(in srgb, var(--app-info) 5%, var(--app-surface));
}

.inline-tool-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-sm);
  padding: 7px 10px;
  font-size: 13px;
  color: var(--app-text);
  cursor: pointer;
  user-select: none;
}

.tool-summary-main {
  gap: 10px;
}

.tool-summary-side {
  gap: var(--app-space-sm);
  flex: 0 0 auto;
}

.tool-status-dot {
  width: 9px;
  height: 9px;
  flex: 0 0 auto;
  border-radius: var(--app-radius-pill);
  background: var(--app-info);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--app-info) 14%, transparent);
}

.tool-state-running .tool-status-dot,
.tool-state-approval .tool-status-dot {
  animation: app-pulse-soft 1.4s ease-in-out infinite;
}

.tool-state-completed .tool-status-dot {
  background: var(--app-success);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--app-success) 16%, transparent);
}

.tool-state-failed .tool-status-dot {
  background: var(--app-error);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--app-error) 16%, transparent);
}

.tool-summary-copy {
  display: grid;
  min-width: 0;
  gap: 1px;
}

.tool-kind {
  color: var(--app-text-muted);
  font-size: 11px;
  line-height: 1.2;
}

.tool-name {
  min-width: 0;
  overflow: hidden;
  color: var(--app-text);
  font-size: 14px;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tool-status-pill {
  padding: 2px 8px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-pill);
  background: var(--app-surface);
  color: var(--app-text-muted);
  font-size: 11px;
  line-height: 1.5;
  white-space: nowrap;
}

.tool-detail {
  border-top: 1px solid var(--app-border);
  background: var(--app-surface);
}

.tool-detail-label {
  padding: var(--app-space-sm) var(--app-space-md) 0;
  color: var(--app-text-muted);
  font-size: 12px;
  font-weight: 600;
}

.inline-tool-part pre {
  max-height: 420px;
  margin: 0;
  padding: var(--app-space-sm) var(--app-space-md) var(--app-space-md);
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
  border-radius: var(--app-radius-sm);
  background: transparent;
}

.tool-empty {
  padding: 0 var(--app-space-md) var(--app-space-md);
  color: var(--app-text-subtle);
  font-size: 12px;
}

.error-part {
  border-color: var(--app-error);
  color: var(--app-error);
}
</style>
