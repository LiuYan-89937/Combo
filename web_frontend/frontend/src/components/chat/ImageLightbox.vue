<template>
  <Teleport to="body">
    <Transition name="lightbox-fade">
      <div
        v-if="open"
        class="image-lightbox"
        role="dialog"
        aria-modal="true"
        :aria-label="t('attachments.imagePreview')"
        @click.self="close"
      >
        <header class="lightbox-toolbar">
          <span class="lightbox-title" :title="activeImage?.name">
            {{ activeImage?.name || t('attachments.imagePreview') }}
          </span>
          <span v-if="images.length > 1" class="lightbox-counter">
            {{ activeIndex + 1 }} / {{ images.length }}
          </span>
          <span class="lightbox-spacer" aria-hidden="true"></span>
          <Transition name="lightbox-status">
            <span
              v-if="actionStatusLabel"
              class="lightbox-status"
              :class="{ 'is-failed': actionFailed }"
              role="status"
            >{{ actionStatusLabel }}</span>
          </Transition>
          <button
            type="button"
            class="lightbox-action"
            :class="{ 'is-success': actionSucceeded, 'is-failed': actionFailed }"
            :disabled="!activeImage?.url || actionBusy"
            @click="copyActive"
          >
            <n-icon :size="15"><CopyOutline /></n-icon>
            <span>{{ actionLabel }}</span>
          </button>
          <button
            type="button"
            class="lightbox-action icon-only"
            :title="t('attachments.openWithSystem')"
            :aria-label="t('attachments.openWithSystem')"
            :disabled="!activeImage || actionBusy"
            @click="openActiveWithSystem"
          >
            <n-icon :size="15"><OpenOutline /></n-icon>
          </button>
          <button
            type="button"
            class="lightbox-action icon-only"
            :title="t('common.close')"
            :aria-label="t('common.close')"
            @click="close"
          >
            <n-icon :size="16"><CloseOutline /></n-icon>
          </button>
        </header>

        <div class="lightbox-stage" @click.self="close">
          <button
            v-if="images.length > 1"
            type="button"
            class="lightbox-nav prev"
            :aria-label="t('attachments.previousImage')"
            @click.stop="step(-1)"
          >‹</button>

          <img
            v-if="activeImage?.url"
            class="lightbox-image"
            :src="activeImage.url"
            :alt="activeImage.name"
            @click.stop
          />
          <p v-else class="lightbox-empty">{{ t('attachments.imageUnavailable') }}</p>

          <button
            v-if="images.length > 1"
            type="button"
            class="lightbox-nav next"
            :aria-label="t('attachments.nextImage')"
            @click.stop="step(1)"
          >›</button>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { NIcon } from 'naive-ui'
import { CloseOutline, CopyOutline, OpenOutline } from '@vicons/ionicons5'
import { useI18n } from '@/composables/useI18n'
import { writeClipboardImage } from '@/utils/clipboard'
import { openAttachmentWithSystemViewer } from '@/utils/systemViewer'
import type { WorkspaceRequestContext, WorkspaceScope } from '@/api/resourceTypes'

export interface LightboxImage {
  url: string
  name: string
  /** Workspace-relative path when the image lives in the workspace. */
  path?: string | null
  scope?: WorkspaceScope | null
  /** Staged upload id, used when the image is still only an upload. */
  attachmentId?: string | null
}

const props = withDefaults(defineProps<{
  open: boolean
  images: LightboxImage[]
  index?: number
  workspaceContext?: WorkspaceRequestContext | null
}>(), {
  index: 0,
  workspaceContext: null,
})

const emit = defineEmits<{
  'update:open': [open: boolean]
  'update:index': [index: number]
}>()

const { t } = useI18n()
type LightboxActionState = 'idle' | 'busy' | 'copied' | 'copyFailed' | 'opened' | 'openFailed'
const actionState = ref<LightboxActionState>('idle')
const failedReason = ref('')
let actionTimer: ReturnType<typeof setTimeout> | null = null

const activeIndex = computed(() => {
  if (props.images.length === 0) return 0
  return Math.min(Math.max(props.index, 0), props.images.length - 1)
})
const activeImage = computed(() => props.images[activeIndex.value] || null)
const actionBusy = computed(() => actionState.value === 'busy')
const actionLabel = computed(() => {
  if (actionState.value === 'copied') return t('attachments.imageCopied')
  if (actionState.value === 'copyFailed') return t('attachments.copyImageFailed')
  return t('attachments.copyImage')
})
// The copy button doubles as the status line for the system-viewer action, so it
// has to report why opening failed rather than falling back to a generic label.
const actionFailed = computed(() => actionState.value === 'copyFailed' || actionState.value === 'openFailed')
const actionSucceeded = computed(() => actionState.value === 'copied' || actionState.value === 'opened')
const actionStatusLabel = computed(() => {
  if (actionState.value === 'opened') return t('attachments.openedInSystem')
  if (actionState.value === 'openFailed') {
    return t('attachments.openWithSystemFailed', { reason: failedReason.value || t('common.unknown') })
  }
  if (actionState.value === 'copyFailed') return t('attachments.copyImageFailed')
  if (actionState.value === 'copied') return t('attachments.imageCopied')
  return ''
})

function resetActionState(): void {
  if (actionTimer) {
    clearTimeout(actionTimer)
    actionTimer = null
  }
  actionState.value = 'idle'
  failedReason.value = ''
}

function flashActionState(state: Exclude<LightboxActionState, 'idle' | 'busy'>): void {
  resetActionState()
  actionState.value = state
  actionTimer = setTimeout(() => { actionState.value = 'idle' }, 1800)
}

function close(): void {
  emit('update:open', false)
}

function step(delta: number): void {
  if (props.images.length < 2) return
  const next = (activeIndex.value + delta + props.images.length) % props.images.length
  emit('update:index', next)
  resetActionState()
}

async function copyActive(): Promise<void> {
  const image = activeImage.value
  if (!image?.url || actionBusy.value) return
  actionState.value = 'busy'
  try {
    await writeClipboardImage(image.url)
    flashActionState('copied')
  } catch {
    flashActionState('copyFailed')
  }
}

/**
 * Hands the current image to the system viewer. The blob URL is passed along so
 * the browser dev server still opens something when no desktop runtime exists.
 */
async function openActiveWithSystem(): Promise<void> {
  const image = activeImage.value
  if (!image || actionBusy.value) return
  try {
    await openAttachmentWithSystemViewer(
      {
        path: image.path,
        scope: image.scope,
        attachmentId: image.attachmentId,
        fallbackUrl: image.url,
      },
      props.workspaceContext,
    )
    flashActionState('opened')
  } catch (error) {
    failedReason.value = error instanceof Error ? error.message : String(error)
    flashActionState('openFailed')
  }
}

function handleKeydown(event: KeyboardEvent): void {
  if (!props.open) return
  if (event.key === 'Escape') close()
  else if (event.key === 'ArrowLeft') step(-1)
  else if (event.key === 'ArrowRight') step(1)
}

watch(() => props.open, (open) => {
  resetActionState()
  if (typeof document === 'undefined') return
  document.documentElement.style.overflow = open ? 'hidden' : ''
})

onBeforeUnmount(() => {
  resetActionState()
  if (typeof window !== 'undefined') window.removeEventListener('keydown', handleKeydown)
  if (typeof document !== 'undefined') document.documentElement.style.overflow = ''
})

if (typeof window !== 'undefined') window.addEventListener('keydown', handleKeydown)
</script>

<style scoped>
.image-lightbox {
  position: fixed;
  z-index: calc(var(--app-z-modal) + 10);
  inset: 0;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  padding: 14px 16px 20px;
  background: color-mix(in srgb, #000 72%, transparent);
  backdrop-filter: blur(14px);
  animation: lightbox-in 0.18s ease both;
}

.lightbox-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  margin-bottom: 10px;
  color: rgba(255, 255, 255, 0.92);
}

.lightbox-title {
  min-width: 0;
  overflow: hidden;
  font-size: 13px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.lightbox-counter {
  flex: none;
  padding: 2px 8px;
  border-radius: var(--app-radius-pill);
  background: rgba(255, 255, 255, 0.14);
  font-size: 11px;
}

.lightbox-spacer { flex: 1; }

/* Status text replaces a toast: the lightbox already owns the viewport, so the
   feedback belongs in its toolbar instead of a floating layer. */
.lightbox-status {
  flex: 0 1 auto;
  max-width: 46%;
  overflow: hidden;
  padding: 3px 9px;
  border-radius: var(--app-radius-pill);
  background: rgba(255, 255, 255, 0.14);
  color: rgba(255, 255, 255, 0.94);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.lightbox-status.is-failed {
  background: color-mix(in srgb, var(--app-diff-deletion) 82%, transparent);
  color: #fff;
}

.lightbox-status-enter-active,
.lightbox-status-leave-active { transition: opacity 0.16s ease; }

.lightbox-status-enter-from,
.lightbox-status-leave-to { opacity: 0; }

.lightbox-action {
  appearance: none;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 11px;
  border: 1px solid rgba(255, 255, 255, 0.22);
  border-radius: var(--app-radius-pill);
  background: rgba(255, 255, 255, 0.1);
  color: rgba(255, 255, 255, 0.94);
  font-size: 12px;
  cursor: pointer;
  transition: background-color var(--app-transition-fast), border-color var(--app-transition-fast);
}

.lightbox-action:hover:not(:disabled) {
  border-color: rgba(255, 255, 255, 0.42);
  background: rgba(255, 255, 255, 0.2);
}

.lightbox-action:disabled {
  opacity: 0.5;
  cursor: default;
}

.lightbox-action.icon-only { padding: 6px; }

.lightbox-action.is-success {
  border-color: color-mix(in srgb, var(--app-success) 70%, transparent);
  background: color-mix(in srgb, var(--app-success) 26%, transparent);
}

.lightbox-action.is-failed {
  border-color: color-mix(in srgb, var(--app-error) 70%, transparent);
  background: color-mix(in srgb, var(--app-error) 24%, transparent);
}

.lightbox-stage {
  position: relative;
  display: grid;
  min-height: 0;
  place-items: center;
}

.lightbox-image {
  display: block;
  max-width: min(96vw, 1400px);
  max-height: 100%;
  border-radius: var(--app-radius-md);
  box-shadow: 0 18px 60px rgba(0, 0, 0, 0.45);
  object-fit: contain;
}

.lightbox-empty {
  margin: 0;
  color: rgba(255, 255, 255, 0.72);
  font-size: 13px;
}

.lightbox-nav {
  position: absolute;
  top: 50%;
  width: 40px;
  height: 40px;
  transform: translateY(-50%);
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.4);
  color: #fff;
  font-size: 22px;
  line-height: 1;
  cursor: pointer;
}

.lightbox-nav:hover { background: rgba(0, 0, 0, 0.62); }
.lightbox-nav.prev { left: 4px; }
.lightbox-nav.next { right: 4px; }

@keyframes lightbox-in {
  from { opacity: 0; }
  to { opacity: 1; }
}

.lightbox-fade-enter-active,
.lightbox-fade-leave-active { transition: opacity 0.16s ease; }

.lightbox-fade-enter-from,
.lightbox-fade-leave-to { opacity: 0; }
</style>
