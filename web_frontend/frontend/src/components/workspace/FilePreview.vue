<template>
  <div class="file-preview-container">
    <div class="preview-header">
      <div class="file-info">
        <n-text strong>{{ file.name }}</n-text>
        <n-text depth="3" style="font-size: 12px">
          {{ formatFileSize(file.sizeBytes) }}
        </n-text>
      </div>
      <n-space>
        <n-button size="small" @click="handleDownload">
          <template #icon>
            <n-icon><Download /></n-icon>
          </template>
          下载
        </n-button>
        <n-button size="small" @click="handleClose">
          <template #icon>
            <n-icon><Close /></n-icon>
          </template>
          关闭
        </n-button>
      </n-space>
    </div>

    <div class="preview-content">
      <!-- 文本/代码 -->
      <div v-if="file.kind === 'text'" class="text-preview">
        <pre><code>{{ file.content }}</code></pre>
      </div>

      <!-- 二进制文件 -->
      <div v-else class="binary-preview">
        <n-empty description="无法预览二进制文件">
          <template #icon>
            <n-icon size="48"><DocumentOutline /></n-icon>
          </template>
          <template #extra>
            <n-button @click="handleDownload">下载文件</n-button>
          </template>
        </n-empty>
      </div>

      <!-- 截断提示 -->
      <n-alert v-if="file.truncated" type="warning" style="margin-top: 12px">
        文件内容已截断，下载完整文件查看全部内容
      </n-alert>
    </div>
  </div>
</template>

<script setup lang="ts">
import { NText, NSpace, NButton, NIcon, NEmpty, NAlert } from 'naive-ui'
import { Download, Close, DocumentOutline } from '@vicons/ionicons5'
import type { WorkspaceFileView } from '@/types/protocol'

const props = defineProps<{
  file: WorkspaceFileView
}>()

const emit = defineEmits<{
  close: []
}>()

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function handleDownload() {
  const blob = new Blob([props.file.content], { type: 'text/plain' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = props.file.name
  a.click()
  URL.revokeObjectURL(url)
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
  padding: 12px 16px;
  border-bottom: 1px solid var(--n-border-color);
}

.file-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.preview-content {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 16px;
  color: #111111;
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

.binary-preview {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
}
</style>
