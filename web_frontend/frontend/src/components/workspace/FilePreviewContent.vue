<template>
  <div class="preview-content" :class="`preview-${previewKind}`" :data-reference-label="file.path || file.name">
    <div
      v-if="previewKind === 'markdown' || previewKind === 'code'"
      ref="markdownPreviewRef"
      class="markdown-preview markdown-content"
      v-html="renderedMarkdown"
    ></div>

    <img
      v-else-if="previewKind === 'image' && previewSource"
      class="image-preview"
      :src="previewSource"
      :alt="file.name"
      :title="t('attachments.viewImage')"
      @click="openPreviewImage"
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
      </n-empty>
    </div>

    <n-alert v-if="previewTruncated" type="warning" class="truncate-alert">
      {{ t('workspace.truncated') }}
    </n-alert>

    <!-- 预览里的内容图片同样走共享查看器：图片预览点了不再毫无反应，
         预览 markdown 里的图片也不再跳新标签。 -->
    <ImageLightbox
      v-model:open="imageViewerOpen"
      v-model:index="imageViewerIndex"
      :images="imageViewerImages"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { NAlert, NEmpty, NIcon } from 'naive-ui'
import { DocumentOutline } from '@/components/icons'
import ImageLightbox from '@/components/chat/ImageLightbox.vue'
import { useI18n } from '@/composables/useI18n'
import { useImageViewer } from '@/composables/useImageViewer'
import { useMarkdownRenderer } from '@/composables/useMarkdownRenderer'
import type { MarkdownImageClickEvent } from '@/rendering/markdown/dom'
import type { WorkspaceFileView } from '@/types/protocol'
import { fileExtension, filePreviewDataUrl, filePreviewKind as resolvePreviewKind } from '@/utils/filePreview'

const props = withDefaults(defineProps<{
  file: WorkspaceFileView
  sourceUrl?: string
}>(), {
  sourceUrl: '',
})

const { t } = useI18n()
const markdownPreviewRef = ref<HTMLElement | null>(null)
const {
  open: imageViewerOpen,
  index: imageViewerIndex,
  images: imageViewerImages,
  showImage,
} = useImageViewer()

/** 预览文件本身是图片时，点击放大它。 */
function openPreviewImage(): void {
  showImage({
    url: previewSource.value,
    name: props.file.name,
    path: props.file.path ?? null,
    scope: props.file.scope ?? null,
  })
}

/** 预览 markdown 正文里的图片同样进查看器（同一组图片可左右切换）。 */
function handleMarkdownImageClick(event: MarkdownImageClickEvent): void {
  const name = (alt: string) => alt || props.file.name
  showImage(
    { url: event.src, name: name(event.alt) },
    event.images.map(image => ({ url: image.src, name: name(image.alt) })),
  )
}

const { renderMarkdown } = useMarkdownRenderer(markdownPreviewRef, {
  onImageClick: handleMarkdownImageClick,
})
const previewKind = computed(() => resolvePreviewKind(props.file))
const previewSource = computed(() => props.sourceUrl || filePreviewDataUrl(props.file))
const renderedMarkdown = computed(() => renderMarkdown(
  previewKind.value === 'code'
    ? `\`\`\`${fileExtension(props.file)}\n${props.file.content || ''}\n\`\`\``
    : props.file.content || '',
  { surface: 'workspace_preview' },
))
const previewTruncated = computed(() => {
  if (!props.file.truncated) return false
  if (props.sourceUrl && ['image', 'pdf'].includes(previewKind.value)) return false
  return true
})
</script>

<style scoped>
.preview-content {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 16px;
  color: var(--app-text);
}

.preview-pdf { padding: 0; }

.text-preview pre {
  margin: 0;
  color: var(--app-text);
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
  cursor: zoom-in;
}

.pdf-preview {
  width: 100%;
  height: 100%;
  border: 0;
  background: var(--app-surface);
}

.binary-preview {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
}

.truncate-alert { margin-top: 12px; }
</style>
