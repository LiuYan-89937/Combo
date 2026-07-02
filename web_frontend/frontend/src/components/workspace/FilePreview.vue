<template>
  <div class="file-preview-container">
    <div class="preview-header">
      <div class="file-info">
        <n-text strong>{{ file.name }}</n-text>
        <n-text depth="3" class="file-meta">
          {{ formatFileSize(file.sizeBytes) }} · {{ previewLabel }}
        </n-text>
      </div>
      <n-space>
        <n-button size="small" @click="handleDownload">
          <template #icon>
            <n-icon><Download /></n-icon>
          </template>
          {{ t('common.download') }}
        </n-button>
        <n-button size="small" @click="handleClose">
          <template #icon>
            <n-icon><Close /></n-icon>
          </template>
          {{ t('common.close') }}
        </n-button>
      </n-space>
    </div>

    <div class="preview-content" :class="`preview-${previewKind}`">
      <div v-if="previewKind === 'markdown'" class="markdown-preview markdown-content" v-html="renderedMarkdown"></div>

      <img
        v-else-if="previewKind === 'image' && previewSource"
        class="image-preview"
        :src="previewSource"
        :alt="file.name"
      />

      <iframe
        v-else-if="previewKind === 'pdf' && previewSource"
        class="pdf-preview"
        :src="previewSource"
        :title="file.name"
      ></iframe>

      <div v-else-if="previewKind === 'text'" class="text-preview">
        <pre><code>{{ file.content }}</code></pre>
      </div>

      <div v-else class="binary-preview">
        <n-empty :description="t('workspace.previewUnsupported')">
          <template #icon>
            <n-icon size="48"><DocumentOutline /></n-icon>
          </template>
          <template #extra>
            <n-button @click="handleDownload">{{ t('workspace.downloadFile') }}</n-button>
          </template>
        </n-empty>
      </div>

      <n-alert v-if="previewTruncated" type="warning" class="truncate-alert">
        {{ t('workspace.truncated') }}
      </n-alert>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NAlert, NButton, NEmpty, NIcon, NSpace, NText } from 'naive-ui'
import { Close, DocumentOutline, Download } from '@vicons/ionicons5'
import { workspaceApi } from '@/api/workspace'
import { useI18n } from '@/composables/useI18n'
import { useMarkdown } from '@/composables/useMarkdown'
import type { WorkspaceScope } from '@/api/resourceTypes'
import type { WorkspaceFileView } from '@/types/protocol'

type PreviewKind = 'text' | 'markdown' | 'image' | 'pdf' | 'unsupported'

const props = defineProps<{
  file: WorkspaceFileView
}>()

const emit = defineEmits<{
  close: []
}>()

const { renderMarkdown } = useMarkdown()
const { t } = useI18n()

const extension = computed(() => props.file.name.split('.').pop()?.toLowerCase() || '')
const mimeType = computed(() => String(props.file.mimeType || '').toLowerCase())
const previewKind = computed<PreviewKind>(() => {
  if (isMarkdownFile()) return 'markdown'
  if (isImageFile()) return 'image'
  if (isPdfFile()) return 'pdf'
  if (props.file.kind === 'text') return 'text'
  return 'unsupported'
})
const previewLabel = computed(() => {
  if (previewKind.value === 'markdown') return 'Markdown'
  if (previewKind.value === 'image') return t('workspace.preview.image')
  if (previewKind.value === 'pdf') return 'PDF'
  if (previewKind.value === 'text' && props.file.payload?.preview_mode === 'extracted_text') return t('workspace.preview.documentText')
  if (previewKind.value === 'text') return t('workspace.preview.text')
  return t('workspace.preview.binary')
})
const renderedMarkdown = computed(() => renderMarkdown(props.file.content || ''))
const packageId = computed(() => {
  const payload = props.file.payload || {}
  return String(payload.package_id || payload.packageId || '').trim() || null
})
const rawFileUrl = computed(() => {
  if (!props.file.path) return ''
  const scope = (props.file.scope || 'workdir') as WorkspaceScope
  return workspaceApi.rawUrl(scope, props.file.path, packageId.value)
})
const dataUrl = computed(() => {
  if (props.file.contentBase64) {
    return `data:${props.file.mimeType || 'application/octet-stream'};base64,${props.file.contentBase64}`
  }
  if (extension.value === 'svg' && props.file.content) {
    return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(props.file.content)}`
  }
  return ''
})
const previewSource = computed(() => rawFileUrl.value || dataUrl.value)
const previewTruncated = computed(() => {
  if (!props.file.truncated) return false
  if (rawFileUrl.value && ['image', 'pdf'].includes(previewKind.value)) return false
  return true
})

function isMarkdownFile(): boolean {
  return props.file.kind === 'text' && ['md', 'markdown', 'mdx'].includes(extension.value)
}

function isImageFile(): boolean {
  return mimeType.value.startsWith('image/') || ['svg', 'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp'].includes(extension.value)
}

function isPdfFile(): boolean {
  return mimeType.value === 'application/pdf' || extension.value === 'pdf'
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function handleDownload() {
  if (rawFileUrl.value) {
    const anchor = document.createElement('a')
    anchor.href = rawFileUrl.value
    anchor.download = props.file.name
    anchor.click()
    return
  }

  const blob = props.file.contentBase64
    ? base64Blob(props.file.contentBase64, props.file.mimeType || 'application/octet-stream')
    : new Blob([props.file.content], { type: props.file.mimeType || 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = props.file.name
  anchor.click()
  URL.revokeObjectURL(url)
}

function base64Blob(content: string, mimeType: string): Blob {
  const binary = atob(content)
  const bytes = new Uint8Array(binary.length)
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index)
  }
  return new Blob([bytes], { type: mimeType })
}

function handleClose() {
  emit('close')
}
</script>

<style scoped>
.file-preview-container {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--n-color);
}

.preview-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--n-border-color);
}

.file-info {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.file-meta {
  font-size: 12px;
}

.preview-content {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 16px;
  color: #111111;
}

.preview-pdf {
  padding: 0;
}

.text-preview pre {
  margin: 0;
  color: #111111;
  font-family: 'SF Mono', Monaco, 'Cascadia Code', 'Roboto Mono', monospace;
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

.markdown-preview {
  max-width: 860px;
  margin: 0 auto;
}

.image-preview {
  display: block;
  max-width: 100%;
  max-height: 100%;
  margin: 0 auto;
  object-fit: contain;
}

.pdf-preview {
  width: 100%;
  height: 100%;
  border: 0;
  background: #ffffff;
}

.binary-preview {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
}

.truncate-alert {
  margin-top: 12px;
}
</style>
