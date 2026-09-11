<template>
  <div class="message-image-gallery" :class="`gallery-${layoutKey}`">
    <div
      v-for="(entry, index) in resolvedEntries"
      :key="entry.id"
      class="gallery-tile"
      :class="{ 'is-single': isSingle, 'is-pending': !entry.url }"
      role="button"
      tabindex="0"
      :title="entry.name"
      :aria-label="t('attachments.viewImage')"
      @click="openAt(index)"
      @keydown.enter.prevent="openAt(index)"
      @keydown.space.prevent="openAt(index)"
    >
      <img v-if="entry.url" :src="entry.url" :alt="entry.name" loading="lazy" />
      <span v-else class="tile-placeholder" aria-hidden="true"></span>

      <span v-if="isSingle" class="tile-caption" :title="entry.name">{{ entry.name }}</span>

      <span class="tile-actions">
        <button
          type="button"
          class="tile-action"
          :title="t('attachments.viewImage')"
          :aria-label="t('attachments.viewImage')"
          @click.stop="openAt(index)"
        >
          <n-icon :size="14"><ExpandOutline /></n-icon>
        </button>
        <button
          type="button"
          class="tile-action"
          :title="t('attachments.copyImage')"
          :aria-label="t('attachments.copyImage')"
          :disabled="!entry.url"
          @click.stop="copyAt(index)"
        >
          <n-icon :size="14"><CopyOutline /></n-icon>
        </button>
        <button
          v-if="entry.openable"
          type="button"
          class="tile-action"
          :title="t('attachments.openInWorkspace')"
          :aria-label="t('attachments.openInWorkspace')"
          @click.stop="openInWorkspace(index)"
        >
          <n-icon :size="14"><OpenOutline /></n-icon>
        </button>
      </span>
    </div>

    <Transition name="gallery-toast">
      <span v-if="toast" class="gallery-toast" :class="`is-${toast.kind}`">{{ toast.text }}</span>
    </Transition>

    <ImageLightbox
      v-model:open="lightboxOpen"
      v-model:index="lightboxIndex"
      :images="lightboxImages"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { NIcon } from 'naive-ui'
import { CopyOutline, ExpandOutline, OpenOutline } from '@vicons/ionicons5'
import ImageLightbox from '@/components/chat/ImageLightbox.vue'
import { useI18n } from '@/composables/useI18n'
import { useWorkspaceFileOpener } from '@/composables/useWorkspaceFileOpener'
import { useWorkspaceResourceUrls } from '@/composables/useWorkspaceResourceUrls'
import { useRuntimeAttachmentObjectUrls } from '@/composables/useRuntimeAttachmentObjectUrls'
import { writeClipboardImage } from '@/utils/clipboard'
import { isImageResource } from '@/utils/workspaceResources'
import type { AttachmentMessagePart } from '@/types/protocol'
import type { WorkspaceRequestContext, WorkspaceScope } from '@/api/resourceTypes'

const props = withDefaults(defineProps<{
  parts: AttachmentMessagePart[]
  workspaceContext?: WorkspaceRequestContext | null
}>(), {
  workspaceContext: null,
})

const { t } = useI18n()
const { openWorkspaceFile } = useWorkspaceFileOpener()

const workspaceContext = computed(() => props.workspaceContext)

/**
 * Images are grouped by the transcript order so a multi-image turn always lays
 * out left-to-right, top-to-bottom, no matter how the object URLs resolve.
 */
const entries = computed(() => props.parts
  .filter(part => isImageResource(part.attachment.name, part.attachment.mime_type))
  .map(part => ({
    id: part.id,
    name: part.attachment.name,
    path: part.attachment.path || '',
    attachmentId: part.attachment.attachment_id || '',
    scope: (part.attachment.workspace_scope || 'workdir') as WorkspaceScope,
    openable: Boolean(part.attachment.path && props.workspaceContext),
  })))

const pathSources = computed(() => entries.value.map(entry => entry.path).filter(Boolean))
const { resolve } = useWorkspaceResourceUrls(pathSources, workspaceContext)
const runtimeIds = computed(() => entries.value.map(entry => entry.attachmentId).filter(Boolean))
const { urls: runtimeUrls } = useRuntimeAttachmentObjectUrls(runtimeIds)

const resolvedEntries = computed(() => entries.value.map(entry => ({
  ...entry,
  url: (entry.path ? resolve(entry.path) : '') || runtimeUrls.value[entry.attachmentId] || '',
})))

const isSingle = computed(() => resolvedEntries.value.length === 1)
const layoutKey = computed(() => {
  const count = resolvedEntries.value.length
  if (count <= 1) return 'single'
  if (count === 2) return 'pair'
  if (count === 3) return 'triple'
  if (count === 4) return 'quad'
  return 'many'
})

const lightboxImages = computed(() => resolvedEntries.value.map(entry => ({
  url: entry.url,
  name: entry.name,
})))
const lightboxOpen = ref(false)
const lightboxIndex = ref(0)
const toast = ref<{ text: string; kind: 'success' | 'failed' } | null>(null)
let toastTimer: ReturnType<typeof setTimeout> | null = null

function showToast(text: string, kind: 'success' | 'failed'): void {
  if (toastTimer) clearTimeout(toastTimer)
  toast.value = { text, kind }
  toastTimer = setTimeout(() => { toast.value = null }, 1800)
}

function openAt(index: number): void {
  const entry = resolvedEntries.value[index]
  if (!entry?.url) {
    showToast(t('attachments.imageUnavailable'), 'failed')
    return
  }
  lightboxIndex.value = index
  lightboxOpen.value = true
}

async function copyAt(index: number): Promise<void> {
  const entry = resolvedEntries.value[index]
  if (!entry?.url) {
    showToast(t('attachments.imageUnavailable'), 'failed')
    return
  }
  try {
    await writeClipboardImage(entry.url)
    showToast(t('attachments.imageCopied'), 'success')
  } catch {
    showToast(t('attachments.copyImageFailed'), 'failed')
  }
}

async function openInWorkspace(index: number): Promise<void> {
  const entry = entries.value[index]
  if (!entry?.openable) return
  await openWorkspaceFile(entry.path, props.workspaceContext, entry.scope)
}
</script>

<style scoped>
.message-image-gallery {
  position: relative;
  display: grid;
  gap: 6px;
  width: fit-content;
  max-width: min(560px, 100%);
  margin-top: 4px;
}

.gallery-single { grid-template-columns: minmax(0, 1fr); }
.gallery-pair,
.gallery-quad { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.gallery-triple,
.gallery-many { grid-template-columns: repeat(3, minmax(0, 1fr)); }

.gallery-tile {
  position: relative;
  aspect-ratio: 1 / 1;
  overflow: hidden;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  background: var(--app-surface-muted);
  cursor: zoom-in;
  transition: border-color var(--app-transition-fast), transform var(--app-transition-fast);
}

.gallery-tile:hover {
  border-color: var(--app-border-hover);
  transform: translateY(-1px);
}

.gallery-tile:focus-visible {
  outline: 2px solid var(--app-primary);
  outline-offset: 2px;
}

.gallery-tile img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.gallery-tile.is-single {
  aspect-ratio: auto;
  overflow: visible;
  border: 0;
  background: transparent;
  transform: none;
  display: grid;
  gap: 5px;
  justify-items: start;
}

.gallery-tile.is-single img {
  width: auto;
  max-width: 100%;
  max-height: 400px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
  box-shadow: var(--app-shadow-sm);
  object-fit: contain;
}

.tile-placeholder {
  display: block;
  width: 100%;
  height: 100%;
  background: linear-gradient(100deg, var(--app-surface-muted) 30%, var(--app-surface-hover) 50%, var(--app-surface-muted) 70%);
  background-size: 220% 100%;
  animation: gallery-skeleton 1.4s ease-in-out infinite;
}

.gallery-tile.is-single .tile-placeholder {
  height: 180px;
  border: 1px dashed var(--app-border);
  border-radius: var(--app-radius-lg);
}

.tile-caption {
  max-width: 100%;
  overflow: hidden;
  color: var(--app-text-muted);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tile-actions {
  position: absolute;
  top: 6px;
  right: 6px;
  display: flex;
  gap: 4px;
  opacity: 0;
  transition: opacity var(--app-transition-fast);
}

.gallery-tile:hover .tile-actions,
.gallery-tile:focus-within .tile-actions { opacity: 1; }

.tile-action {
  appearance: none;
  display: grid;
  width: 24px;
  height: 24px;
  place-items: center;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.55);
  color: #fff;
  cursor: pointer;
  transition: background-color var(--app-transition-fast);
}

.tile-action:hover:not(:disabled) { background: rgba(0, 0, 0, 0.75); }
.tile-action:disabled { opacity: 0.45; cursor: default; }

.gallery-toast {
  position: absolute;
  bottom: 8px;
  left: 50%;
  z-index: 2;
  padding: 4px 10px;
  transform: translateX(-50%);
  border-radius: var(--app-radius-pill);
  background: color-mix(in srgb, var(--app-text) 82%, transparent);
  color: var(--app-surface);
  font-size: 11px;
  white-space: nowrap;
}

.gallery-toast.is-failed {
  background: color-mix(in srgb, var(--app-error) 88%, transparent);
  color: #fff;
}

.gallery-toast-enter-active,
.gallery-toast-leave-active { transition: opacity 0.16s ease, transform 0.16s ease; }

.gallery-toast-enter-from,
.gallery-toast-leave-to {
  opacity: 0;
  transform: translate(-50%, 4px);
}

@keyframes gallery-skeleton {
  from { background-position: 120% 0; }
  to { background-position: -120% 0; }
}
</style>
