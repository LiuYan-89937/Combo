<template>
  <div class="message-input-container" @dragover.prevent @drop.prevent="handleFileDrop">
    <div v-if="contextReferences.length > 0" class="attachments-preview context-references-preview">
      <div
        v-for="(reference, index) in contextReferences"
        :key="`${reference.source_kind}:${reference.name}:${index}`"
        class="attachment-item context-reference-item"
      >
        <ResourceIcon
          :name="reference.name"
          :mime-type="reference.mime_type"
          :kind="reference.source_kind === 'workspace_file' ? 'file' : 'text'"
          :size="18"
        />
        <span class="attachment-name">{{ reference.name }}</span>
        <n-text depth="3" class="reference-kind">{{ referenceKindLabel(reference.source_kind) }}</n-text>
        <n-button text size="small" @click="referenceStore.remove(index, normalizedReferenceScope)">
          <n-icon><Close /></n-icon>
        </n-button>
      </div>
    </div>

    <!-- 附件预览区 -->
    <div v-if="attachmentsEnabled && attachments.length > 0" class="attachments-preview">
      <div
        v-for="(attachment, index) in attachments"
        :key="index"
        class="attachment-item"
      >
        <ResourceIcon
          :name="attachment.name"
          :mime-type="attachment.mime_type"
          :kind="attachment.kind"
          :size="18"
        />
        <span class="attachment-name">{{ attachment.name }}</span>
        <n-button text size="small" @click="removeAttachment(index)">
          <n-icon><Close /></n-icon>
        </n-button>
      </div>
      <n-text depth="3" class="attachment-count">
        {{ t('attachments.limitHint', { count: attachments.length, max: maxAttachments }) }}
      </n-text>
    </div>

    <!-- 输入框 -->
    <div class="input-wrapper">
      <n-input
        ref="inputRef"
        v-model:value="inputText"
        type="textarea"
        :placeholder="placeholder"
        :disabled="disabled"
        :rows="rows"
        :autosize="{ minRows: rows, maxRows: maxRows }"
        @update:value="handleTextUpdate"
        @keydown="handleKeyDown"
        @paste="handlePaste"
      />
    </div>

    <!-- 操作栏 -->
    <div class="input-actions">
      <div class="left-actions">
        <n-button
          v-if="attachmentsEnabled"
          text
          @click="openAttachmentPicker"
          :disabled="disabled || remainingAttachmentSlots <= 0"
        >
          <template #icon>
            <n-icon><AttachOutline /></n-icon>
          </template>
          {{ t('attachments.add') }}
        </n-button>
        <input
          ref="attachmentFileInputRef"
          class="native-file-input"
          type="file"
          multiple
          :accept="fileCapabilities?.attachment_accept || ''"
          @change="handleAttachmentFileInput"
        />

        <n-select
          v-if="modelSelectorEnabled"
          class="model-selector"
          size="small"
          :value="selectedModelProfileId || ''"
          :options="modelOptions"
          :placeholder="t('chat.modelSelectorPlaceholder')"
          :disabled="disabled || modelOptions.length <= 1"
          filterable
          @update:value="handleModelSelect"
        />

        <n-popover v-if="reasoningControlEnabled" trigger="click" placement="top-start">
          <template #trigger>
            <n-button
              text
              class="reasoning-button"
              :disabled="disabled"
              :aria-label="t('chat.reasoningLabel')"
            >
              <template #icon>
                <n-icon><BulbOutline /></n-icon>
              </template>
              <span>{{ t('chat.reasoningLabel') }} · {{ reasoningLabel }}</span>
              <n-icon size="12" class="reasoning-caret"><CaretDown /></n-icon>
            </n-button>
          </template>
          <div class="reasoning-popover">
            <div class="reasoning-popover-header">
              <span>{{ t('chat.reasoningIntensity') }}</span>
            </div>
            <n-radio-group
              :value="reasoningSelectionValue"
              size="small"
              class="reasoning-options soft-segmented-control"
              :disabled="disabled"
              @update:value="handleReasoningSelect"
            >
              <n-radio-button
                v-for="option in reasoningOptions"
                :key="option.value"
                :value="option.value"
              >
                {{ option.label }}
              </n-radio-button>
            </n-radio-group>
          </div>
        </n-popover>

        <n-button
          v-if="!attachmentsEnabled"
          text
          disabled
          class="input-mode-label"
        >
          <template #icon>
            <n-icon><CodeSlash /></n-icon>
          </template>
          {{ t('attachments.textMode') }}
        </n-button>

        <slot name="auxiliary-action"></slot>
      </div>

      <div class="right-actions">
        <n-text
          v-if="inputText.length > 0"
          depth="3"
          class="character-count"
          aria-live="polite"
        >
          {{ t('attachments.characterCount', { count: inputText.length }) }}
        </n-text>

        <n-button
          type="primary"
          class="send-button"
          :disabled="!canSend"
          :aria-label="t('common.send')"
          @click="handleSend"
        >
          {{ isRunning ? t('chat.queueSend') : t('common.send') }}
          <span v-if="queuedCount > 0" class="queued-count">
            {{ t('chat.queuedCount', { count: queuedCount }) }}
          </span>
          <template #icon>
            <n-icon><Send /></n-icon>
          </template>
        </n-button>

        <n-button
          v-if="isRunning"
          type="error"
          class="cancel-button"
          :aria-label="t('common.cancel')"
          @click="handleCancel"
        >
          {{ t('common.cancel') }}
          <template #icon>
            <n-icon><Stop /></n-icon>
          </template>
        </n-button>
      </div>
    </div>

    <!-- 附件选择器 -->
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted } from 'vue'
import { NInput, NButton, NIcon, NText, NPopover, NRadioButton, NRadioGroup, NSelect, useMessage } from 'naive-ui'
import { AttachOutline, BulbOutline, CaretDown, Close, CodeSlash, Send, Stop } from '@/components/icons'
import ResourceIcon from '@/components/common/ResourceIcon.vue'
import { useI18n } from '@/composables/useI18n'
import { useFileCapabilities } from '@/composables/useFileCapabilities'
import { MAX_RUNTIME_ATTACHMENTS, extensionFromMimeType, pastedImageFiles, runtimeFileAttachmentFromFile } from '@/utils/attachments'
import type { RuntimeAttachmentInput } from '@/types/protocol'
import { useContextReferenceStore } from '@/stores/contextReferences'

const { t } = useI18n()
const messageApi = useMessage()
const referenceStore = useContextReferenceStore()
const {
  capabilities: fileCapabilities,
  attachmentExtensions,
  error: fileCapabilitiesError,
  load: loadFileCapabilities,
} = useFileCapabilities()

const props = withDefaults(
  defineProps<{
    placeholder?: string
    disabled?: boolean
    isRunning?: boolean
    queuedCount?: number
    rows?: number
    maxRows?: number
    attachmentsEnabled?: boolean
    modelSelectorEnabled?: boolean
    modelOptions?: Array<{ label: string; value: string; disabled?: boolean }>
    selectedModelProfileId?: string | null
    reasoningControlEnabled?: boolean
    reasoningIntensity?: number | null
    referenceScope?: string
  }>(),
  {
    placeholder: '',
    disabled: false,
    isRunning: false,
    queuedCount: 0,
    rows: 3,
    maxRows: 10,
    attachmentsEnabled: true,
    modelSelectorEnabled: false,
    modelOptions: () => [],
    selectedModelProfileId: '',
    reasoningControlEnabled: false,
    reasoningIntensity: null,
    referenceScope: 'global',
  }
)

const emit = defineEmits<{
  send: [message: string, attachments: RuntimeAttachmentInput[]]
  cancel: []
  input: [value: string]
  'update:selectedModelProfileId': [value: string]
  'update:reasoningIntensity': [value: number | null]
}>()

const inputRef = ref()
const attachmentFileInputRef = ref<HTMLInputElement | null>(null)
const inputText = ref('')
const attachments = ref<RuntimeAttachmentInput[]>([])
const normalizedReferenceScope = computed(() => String(props.referenceScope || '').trim() || 'global')
const contextReferences = computed(() => referenceStore.references(normalizedReferenceScope.value))
const placeholder = computed(() => props.placeholder || t('chat.inputPlaceholder'))
const reasoningOptions = computed(() => [
  { label: t('chat.reasoningDefault'), value: -1 },
  { label: t('chat.reasoningOff'), value: 0 },
  { label: t('chat.reasoningLow'), value: 1 },
  { label: t('chat.reasoningMedium'), value: 2 },
  { label: t('chat.reasoningHigh'), value: 3 },
  { label: t('chat.reasoningMaximum'), value: 4 },
])
const reasoningSelectionValue = computed(() => props.reasoningIntensity ?? -1)
const reasoningLabel = computed(() => (
  reasoningOptions.value.find((option) => option.value === reasoningSelectionValue.value)?.label
  || reasoningOptions.value[0].label
))
const maxAttachments = MAX_RUNTIME_ATTACHMENTS
const remainingAttachmentSlots = computed(() => Math.max(0, maxAttachments - attachments.value.length - contextReferences.value.length))

const canSend = computed(() => {
  const hasText = inputText.value.trim().length > 0
  const hasAttachments = props.attachmentsEnabled && attachments.value.length > 0
  return (hasText || hasAttachments) && !props.disabled
})

function handleKeyDown(e: KeyboardEvent) {
  if (e.key !== 'Enter' || e.shiftKey || e.isComposing) return
  e.preventDefault()
  handleSend()
}

function handleTextUpdate(value: string) {
  inputText.value = value
  emit('input', value)
}

async function handlePaste(e: ClipboardEvent) {
  if (!props.attachmentsEnabled || props.disabled) return
  const files = pastedImageFiles(e, pastedImageName)
  if (files.length === 0) return
  e.preventDefault()
  const selectedFiles = files.slice(0, remainingAttachmentSlots.value)
  if (selectedFiles.length === 0) {
    showAttachmentLimitReached()
    return
  }
  const pastedAttachments = await Promise.all(selectedFiles.map((file) => runtimeFileAttachmentFromFile(file)))
  appendAttachments(pastedAttachments)
  if (selectedFiles.length < files.length) {
    showAttachmentLimitPartial(selectedFiles.length)
  }
}

function handleSend() {
  if (!canSend.value) return

  const message = inputText.value.trim()
  emit('send', message, props.attachmentsEnabled ? [...contextReferences.value, ...attachments.value] : [...contextReferences.value])

  // 清空输入
  inputText.value = ''
  attachments.value = []
  referenceStore.clear(normalizedReferenceScope.value)
}

function handleCancel() {
  emit('cancel')
}

function handleModelSelect(value: string) {
  emit('update:selectedModelProfileId', value || '')
}

function handleReasoningSelect(value: string | number) {
  const intensity = Number(value)
  emit('update:reasoningIntensity', intensity < 0 ? null : intensity)
}

function openAttachmentPicker() {
  if (!fileCapabilities.value) {
    messageApi.warning(fileCapabilitiesError.value || t('attachments.capabilitiesUnavailable'))
    void loadFileCapabilities()
    return
  }
  attachmentFileInputRef.value?.click()
}

async function handleAttachmentFileInput(event: Event) {
  const input = event.target as HTMLInputElement
  await appendFiles(Array.from(input.files || []))
  input.value = ''
}

async function handleFileDrop(event: DragEvent) {
  if (!props.attachmentsEnabled || props.disabled) return
  await appendFiles(Array.from(event.dataTransfer?.files || []))
}

async function appendFiles(files: File[]) {
  if (files.length === 0) return
  const accepted: File[] = []
  const rejected: string[] = []
  for (const file of files) {
    if (isAcceptedAttachmentFile(file)) accepted.push(file)
    else rejected.push(file.name)
  }
  if (rejected.length) {
    messageApi.warning(t('attachments.unsupportedFiles', { names: rejected.join(', ') }))
  }
  const selected = accepted.slice(0, remainingAttachmentSlots.value)
  if (selected.length < accepted.length) showAttachmentLimitPartial(selected.length)
  appendAttachments(await Promise.all(selected.map((file) => runtimeFileAttachmentFromFile(file))))
}

function isAcceptedAttachmentFile(file: File): boolean {
  const suffix = file.name.includes('.') ? `.${file.name.split('.').pop()?.toLowerCase()}` : ''
  return Boolean(suffix && attachmentExtensions.value.has(suffix))
}

function appendAttachments(nextAttachments: RuntimeAttachmentInput[]) {
  if (nextAttachments.length === 0) return
  const remaining = remainingAttachmentSlots.value
  if (remaining <= 0) {
    showAttachmentLimitReached()
    return
  }
  const accepted = nextAttachments.slice(0, remaining)
  attachments.value.push(...accepted)
  if (accepted.length < nextAttachments.length) {
    showAttachmentLimitPartial(accepted.length)
  }
}

function showAttachmentLimitReached() {
  messageApi.warning(t('attachments.limitReached', { max: maxAttachments }))
}

function showAttachmentLimitPartial(accepted: number) {
  messageApi.warning(t('attachments.limitPartial', { accepted, max: maxAttachments }))
}

function pastedImageName(file: File, index: number) {
  const indexSuffix = index > 0 ? `-${index + 1}` : ''
  return `${t('attachments.pastedImageName')}-${pasteTimestamp()}${indexSuffix}.${extensionFromMimeType(file.type)}`
}

function pasteTimestamp() {
  const now = new Date()
  const date = [now.getFullYear(), pad2(now.getMonth() + 1), pad2(now.getDate())].join('')
  const time = [pad2(now.getHours()), pad2(now.getMinutes()), pad2(now.getSeconds())].join('')
  return `${date}-${time}`
}

function pad2(value: number) {
  return String(value).padStart(2, '0')
}

function removeAttachment(index: number) {
  attachments.value.splice(index, 1)
}

function referenceKindLabel(sourceKind?: string): string {
  if (sourceKind === 'workspace_file') return t('references.workspaceFile')
  if (sourceKind === 'text_selection') return t('references.selection')
  return t('references.message')
}

// 聚焦输入框
function focus() {
  nextTick(() => {
    inputRef.value?.focus()
  })
}

function clearTrailingAtMention() {
  inputText.value = inputText.value.replace(/@[^\s@]*$/, '')
  emit('input', inputText.value)
  focus()
}

watch(
  normalizedReferenceScope,
  scope => referenceStore.activate(scope),
  { immediate: true },
)

watch(
  () => props.attachmentsEnabled,
  (enabled) => {
    if (!enabled) {
      attachments.value = []
    }
  }
)

onMounted(() => {
  void loadFileCapabilities()
})

// 暴露方法
defineExpose({
  focus,
  clearTrailingAtMention,
})
</script>

<style scoped>
.message-input-container {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-md);
  padding: var(--app-space-md);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-xl);
  background: var(--app-surface);
  transition: border-color var(--app-transition-base), box-shadow var(--app-transition-base);
}

.message-input-container:focus-within {
  border-color: var(--app-border-focus);
  box-shadow: 0 0 0 3px var(--app-focus-shadow);
}

.native-file-input {
  display: none;
}

.attachments-preview {
  display: flex;
  flex-wrap: wrap;
  gap: var(--app-space-sm);
  padding: var(--app-space-sm) var(--app-space-md);
  background: var(--app-surface-muted);
  border-radius: var(--app-radius-md);
  animation: app-fade-in 0.2s ease both;
}

.attachment-item {
  display: flex;
  align-items: center;
  gap: var(--app-space-xs);
  padding: var(--app-space-xs) var(--app-space-sm);
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  font-size: var(--app-font-md);
  transition: border-color var(--app-transition-fast), transform var(--app-transition-fast);
  animation: app-pop-in 0.22s cubic-bezier(0.16, 1, 0.3, 1) both;
}

.attachment-item:hover {
  border-color: var(--app-border-hover);
}

.attachment-name {
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.attachment-count {
  align-self: center;
  margin-left: auto;
  font-size: var(--app-font-sm);
  white-space: nowrap;
}

.reference-kind {
  font-size: var(--app-font-sm);
  white-space: nowrap;
}

.input-wrapper {
  position: relative;
}

.input-wrapper :deep(.n-input) {
  --n-border: none !important;
  --n-border-hover: none !important;
  --n-border-focus: none !important;
  --n-box-shadow-focus: none !important;
  background: transparent;
}

.input-wrapper :deep(.n-input .n-input__textarea-el) {
  color: var(--app-text);
  padding: var(--app-space-xs) 0;
  font-size: var(--app-font-lg);
  line-height: var(--app-leading-normal);
}

.input-wrapper :deep(.n-input .n-input__placeholder) {
  color: var(--app-text-placeholder);
}

.input-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-sm);
}

.left-actions,
.right-actions {
  display: flex;
  align-items: center;
  gap: var(--app-space-sm);
  min-width: 0;
}

.model-selector {
  width: 180px;
}

.reasoning-button {
  gap: var(--app-space-xs);
  white-space: nowrap;
}

.reasoning-caret {
  color: var(--app-text-muted);
}

.reasoning-popover {
  width: max-content;
  max-width: min(420px, calc(100vw - 32px));
  padding: var(--app-space-xs);
}

.reasoning-popover-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-sm);
  margin-bottom: var(--app-space-sm);
  color: var(--app-text-secondary);
  font-size: var(--app-font-sm);
}

.reasoning-options {
  display: flex;
  width: 100%;
}

.reasoning-options :deep(.n-radio-button) {
  flex: 1;
  text-align: center;
}

.character-count {
  font-size: var(--app-font-sm);
  font-variant-numeric: tabular-nums;
  animation: app-fade-in 0.16s ease both;
}

.send-button,
.cancel-button {
  border-radius: var(--app-radius-md);
  transition: transform var(--app-transition-fast);
}

.queued-count {
  margin-left: var(--app-space-xs);
  font-size: var(--app-font-xs);
  opacity: 0.78;
}

.send-button:not(:disabled):active,
.cancel-button:not(:disabled):active {
  transform: scale(0.96);
}

@media (max-width: 768px) {
  .model-selector {
    width: 150px;
  }
}

.cancel-button {
  animation: app-pop-in 0.22s cubic-bezier(0.16, 1, 0.3, 1) both;
}
</style>
