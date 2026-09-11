<template>
  <div class="message-image-gallery" :style="attachmentTileStyle">
    <div
      v-for="(entry, index) in resolvedEntries"
      :key="entry.id"
      class="gallery-tile"
      :class="{ 'is-pending': !entry.url }"
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

      <span class="tile-actions">
        <button
          type="button"
          class="tile-action"
          :title="t('attachments.viewImage')"
          :aria-label="t('attachments.viewImage')"
          @click.stop="openAt(index)"
        >
          <n-icon :size="13"><ExpandOutline /></n-icon>
        </button>
        <button
          type="button"
          class="tile-action"
          :title="t('attachments.copyImage')"
          :aria-label="t('attachments.copyImage')"
          :disabled="!entry.url"
          @click.stop="copyAt(index)"
        >
          <n-icon :size="13"><CopyOutline /></n-icon>
        </button>
        <button
          v-if="entry.openable || entry.attachmentId"
          type="button"
          class="tile-action"
          :title="t('attachments.openWithSystem')"
          :aria-label="t('attachments.openWithSystem')"
          @click.stop="openWithSystem(index)"
        >
          <n-icon :size="13"><OpenOutline /></n-icon>
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
      :workspace-context="workspaceContext"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { NIcon } from 'naive-ui'
import { CopyOutline, ExpandOutline, OpenOutline } from '@vicons/ionicons5'
import ImageLightbox from '@/components/chat/ImageLightbox.vue'
import { useI18n } from '@/composables/useI18n'
import { useWorkspaceResourceUrls } from '@/composables/useWorkspaceResourceUrls'
import { useRuntimeAttachmentObjectUrls } from '@/composables/useRuntimeAttachmentObjectUrls'
import { writeClipboardImage } from '@/utils/clipboard'
import { attachmentTileVars } from '@/utils/attachmentTiles'
import { openAttachmentWithSystemViewer } from '@/utils/systemViewer'
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

const attachmentTileStyle = attachmentTileVars()
const workspaceContext = computed(() => props.workspaceContext)

/**
 * Images are grouped by transcript order so a multi-image turn always lays out
 * left-to-right, top-to-bottom, no matter how the object URLs resolve.
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

const lightboxImages = computed(() => resolvedEntries.value.map(entry => ({
  url: entry.url,
  name: entry.name,
  path: entry.path,
  scope: entry.scope,
  attachmentId: entry.attachmentId,
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

async function openWithSystem(index: number): Promise<void> {
  const entry = resolvedEntries.value[index]
  if (!entry) return
  try {
    await openAttachmentWithSystemViewer(
      {
        path: entry.path,
        scope: entry.scope,
        attachmentId: entry.attachmentId,
        fallbackUrl: entry.url,
      },
      props.workspaceContext,
    )
    showToast(t('attachments.openedInSystem'), 'success')
  } catch (error) {
    showToast(
      t('attachments.openWithSystemFailed', {
        reason: error instanceof Error ? error.message : String(error),
      }),
      'failed',
    )
  }
}
</script>

<style scoped>
/*
 * Fixed-size tiles in a wrapping row. The previous layout changed both the
 * column count and the tile size with the number of images, which is what made
 * a multi-image turn look uneven.
 */
.message-image-gallery {
  position: relative;
  display: flex;
  flex-wrap: wrap;
  gap: var(--attachment-tile-gap, 8px);
  max-width: 100%;
  margin-top: 4px;
}

.gallery-tile {
  position: relative;
  width: var(--attachment-tile-size, 80px);
  height: var(--attachment-tile-size, 80px);
  flex: 0 0 var(--attachment-tile-size, 80px);
  overflow: hidden;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  background: color-mix(in srgb, var(--app-text) 4%, transparent);
  cursor: zoom-in;
  transition: border-color var(--app-transition-fast);
}

.gallery-tile:hover {
  border-color: var(--app-border-hover);
}

.gallery-tile:focus-visible {
  outline: 2px solid var(--app-text);
  outline-offset: 2px;
}

.gallery-tile img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.tile-placeholder {
  display: block;
  width: 100%;
  height: 100%;
  background: linear-gradient(100deg, transparent 30%, color-mix(in srgb, var(--app-text) 8%, transparent) 50%, transparent 70%);
  background-size: 220% 100%;
  animation: gallery-skeleton 1.4s ease-in-out infinite;
}

/* Hover actions are centred because three 22px buttons and their gaps only just
   fit inside an 80px tile. */
.tile-actions {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  background: color-mix(in srgb, var(--app-text) 32%, transparent);
  opacity: 0;
  transition: opacity var(--app-transition-fast);
}

.gallery-tile:hover .tile-actions,
.gallery-tile:focus-within .tile-actions { opacity: 1; }

.tile-action {
  appearance: none;
  display: grid;
  width: 22px;
  height: 22px;
  place-items: center;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: color-mix(in srgb, var(--app-text) 78%, transparent);
  color: var(--app-text-inverse);
  cursor: pointer;
  transition: background-color var(--app-transition-fast);
}

.tile-action:hover:not(:disabled) {
  background: var(--app-text);
}

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
  color: var(--app-text-inverse);
  font-size: 11px;
  white-space: nowrap;
}

.gallery-toast.is-failed {
  background: var(--app-diff-deletion);
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
