<template>
  <div class="message-input-container">
    <!-- 附件预览区 -->
    <div v-if="attachmentsEnabled && attachments.length > 0" class="attachments-preview">
      <div
        v-for="(attachment, index) in attachments"
        :key="index"
        class="attachment-item"
      >
        <n-icon size="18">
          <Document v-if="attachment.kind === 'file'" />
          <Link v-else-if="attachment.kind === 'url'" />
          <Text v-else />
        </n-icon>
        <span class="attachment-name">{{ attachment.name }}</span>
        <n-button text size="small" @click="removeAttachment(index)">
          <n-icon><Close /></n-icon>
        </n-button>
      </div>
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
        @keydown="handleKeyDown"
      />
    </div>

    <!-- 操作栏 -->
    <div class="input-actions">
      <div class="left-actions">
        <n-button v-if="attachmentsEnabled" text @click="showAttachmentPicker = true" :disabled="disabled">
          <template #icon>
            <n-icon><AttachOutline /></n-icon>
          </template>
          {{ t('attachments.add') }}
        </n-button>

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
      @attach="handleAttach"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'
import { NInput, NButton, NIcon, NText, NPopover } from 'naive-ui'
import { AttachOutline, Document, Link, Text, Close, CodeSlash, Send, Stop } from '@vicons/ionicons5'
import AttachmentPickerModal from './AttachmentPickerModal.vue'
import { useI18n } from '@/composables/useI18n'
import type { RuntimeAttachmentInput } from '@/types/protocol'

const { t } = useI18n()

const props = withDefaults(
  defineProps<{
    placeholder?: string
    disabled?: boolean
    isRunning?: boolean
    rows?: number
    maxRows?: number
    attachmentsEnabled?: boolean
  }>(),
  {
    placeholder: '',
    disabled: false,
    isRunning: false,
    rows: 3,
    maxRows: 10,
    attachmentsEnabled: true,
  }
)

const emit = defineEmits<{
  send: [message: string, attachments: RuntimeAttachmentInput[]]
  cancel: []
}>()

const inputRef = ref()
const inputText = ref('')
const attachments = ref<RuntimeAttachmentInput[]>([])
const showAttachmentPicker = ref(false)
const placeholder = computed(() => props.placeholder || t('chat.inputPlaceholder'))

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

function handleSend() {
  if (!canSend.value) return

  const message = inputText.value.trim()
  emit('send', message, props.attachmentsEnabled ? attachments.value : [])

  // 清空输入
  inputText.value = ''
  attachments.value = []
}

function handleCancel() {
  emit('cancel')
}

function handleAttach(attachment: RuntimeAttachmentInput) {
  if (!props.attachmentsEnabled) return
  attachments.value.push(attachment)
}

function removeAttachment(index: number) {
  attachments.value.splice(index, 1)
}

// 聚焦输入框
function focus() {
  nextTick(() => {
    inputRef.value?.focus()
  })
}

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

.character-count {
  font-size: var(--app-font-sm);
  font-variant-numeric: tabular-nums;
  animation: app-fade-in 0.16s ease both;
}

.send-button,
.cancel-button {
  transition: transform var(--app-transition-fast);
}

.send-button:not(:disabled):active,
.cancel-button:not(:disabled):active {
  transform: scale(0.96);
}

.cancel-button {
  animation: app-pop-in 0.22s cubic-bezier(0.16, 1, 0.3, 1) both;
}
</style>
