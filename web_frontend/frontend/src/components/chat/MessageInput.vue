<template>
  <div class="message-input-container">
    <div v-if="contextReferences.length > 0" class="attachments-preview context-references-preview">
      <div
        v-for="(reference, index) in contextReferences"
        :key="`${reference.source_kind}:${reference.name}:${index}`"
        class="attachment-item context-reference-item"
      >
        <n-icon size="18">
          <Document v-if="reference.source_kind === 'workspace_file'" />
          <Text v-else />
        </n-icon>
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
        <n-icon size="18">
          <ImageOutline v-if="isImageAttachment(attachment)" />
          <Document v-else-if="attachment.kind === 'file'" />
          <Link v-else-if="attachment.kind === 'url'" />
          <Text v-else />
        </n-icon>
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
          @click="showAttachmentPicker = true"
          :disabled="disabled || remainingAttachmentSlots <= 0"
        >
          <template #icon>
            <n-icon><AttachOutline /></n-icon>
          </template>
          {{ t('attachments.add') }}
        </n-button>

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
              <span>{{ t('chat.reasoningLabel') }}</span>
              <n-text depth="3" class="reasoning-value">{{ reasoningLabel }}</n-text>
            </n-button>
          </template>
          <div class="reasoning-popover">
            <div class="reasoning-popover-header">
              <span>{{ t('chat.reasoningIntensity') }}</span>
              <n-button text size="tiny" @click="emit('update:reasoningIntensity', null)">
                {{ t('chat.reasoningDefault') }}
              </n-button>
            </div>
            <n-slider
              :value="reasoningSliderValue"
              :min="REASONING_SLIDER_DEFAULT"
              :max="REASONING_SLIDER_MAX"
              :step="1"
              :marks="reasoningMarks"
              :disabled="disabled"
              @update:value="handleReasoningSliderChange"
            />
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

        <n-popover trigger="hover" placement="top">
          <template #trigger>
            <n-button text :disabled="disabled">
              <template #icon>
                <n-icon><CodeSlash /></n-icon>
              </template>
            </n-button>
          </template>
          {{ t('attachments.markdownHint') }}
        </n-popover>
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
          v-if="!isRunning"
          type="primary"
          class="send-button"
          :disabled="!canSend"
          :aria-label="t('common.send')"
          @click="handleSend"
        >
          {{ t('common.send') }}
          <template #icon>
            <n-icon><Send /></n-icon>
          </template>
        </n-button>

        <n-button
          v-else
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
    <AttachmentPickerModal
      v-if="attachmentsEnabled"
      v-model:show="showAttachmentPicker"
      :current-count="attachments.length + contextReferences.length"
      :max-count="maxAttachments"
      @attach="handleAttach"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'
import { NInput, NButton, NIcon, NText, NPopover, NSelect, NSlider, useMessage } from 'naive-ui'
import { AttachOutline, BulbOutline, Document, Link, Text, Close, CodeSlash, Send, Stop, ImageOutline } from '@/components/icons'
import AttachmentPickerModal from './AttachmentPickerModal.vue'
import { useI18n } from '@/composables/useI18n'
import { MAX_RUNTIME_ATTACHMENTS, extensionFromMimeType, pastedImageFiles, runtimeFileAttachmentFromFile } from '@/utils/attachments'
import { REASONING_SLIDER_DEFAULT, REASONING_SLIDER_MAX } from '@/utils/reasoning'
import type { RuntimeAttachmentInput } from '@/types/protocol'
import { useContextReferenceStore } from '@/stores/contextReferences'

const { t } = useI18n()
const messageApi = useMessage()
const referenceStore = useContextReferenceStore()

const props = withDefaults(
  defineProps<{
    placeholder?: string
    disabled?: boolean
    isRunning?: boolean
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
const inputText = ref('')
const attachments = ref<RuntimeAttachmentInput[]>([])
const normalizedReferenceScope = computed(() => String(props.referenceScope || '').trim() || 'global')
const contextReferences = computed(() => referenceStore.references(normalizedReferenceScope.value))
const showAttachmentPicker = ref(false)
const placeholder = computed(() => props.placeholder || t('chat.inputPlaceholder'))
const reasoningSliderValue = computed(() => props.reasoningIntensity === null ? REASONING_SLIDER_DEFAULT : props.reasoningIntensity + 1)
const reasoningLabels = computed(() => [
  t('chat.reasoningDefault'),
  t('chat.reasoningOff'),
  t('chat.reasoningLow'),
  t('chat.reasoningMedium'),
  t('chat.reasoningHigh'),
  t('chat.reasoningMaximum'),
])
const reasoningLabel = computed(() => reasoningLabels.value[reasoningSliderValue.value] || reasoningLabels.value[0])
const reasoningMarks = computed(() => Object.fromEntries(reasoningLabels.value.map((label, index) => [index, label])))
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

function handleReasoningSliderChange(value: number | [number, number]) {
  const sliderValue = Array.isArray(value) ? value[0] : value
  emit('update:reasoningIntensity', sliderValue === REASONING_SLIDER_DEFAULT ? null : sliderValue - 1)
}

function handleAttach(attachment: RuntimeAttachmentInput | RuntimeAttachmentInput[]) {
  if (!props.attachmentsEnabled) return
  appendAttachments(Array.isArray(attachment) ? attachment : [attachment])
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

function isImageAttachment(attachment: RuntimeAttachmentInput) {
  return attachment.kind === 'file' && attachment.mime_type?.startsWith('image/')
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
      showAttachmentPicker.value = false
    }
  }
)

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

.reasoning-value {
  font-size: var(--app-font-sm);
}

.reasoning-popover {
  width: 280px;
  padding: var(--app-space-xs) var(--app-space-sm) var(--app-space-md);
}

.reasoning-popover-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-sm);
  margin-bottom: var(--app-space-lg);
  color: var(--app-text-secondary);
  font-size: var(--app-font-sm);
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
