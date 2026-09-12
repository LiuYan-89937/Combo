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
          <div
            class="lightbox-zoom"
            role="group"
            :title="t('attachments.zoomHint')"
          >
            <button
              type="button"
              class="lightbox-action icon-only"
              :title="t('attachments.zoomOut')"
              :aria-label="t('attachments.zoomOut')"
              :disabled="!activeImage?.url || scale <= minScale + 1e-6"
              @click="zoomBy(1 / ZOOM_STEP)"
            >
              <n-icon :size="16"><RemoveOutline /></n-icon>
            </button>
            <button
              type="button"
              class="lightbox-action lightbox-zoom-value"
              :title="t('attachments.zoomHint')"
              :disabled="!activeImage?.url"
              @click="zoomToActualSize"
            >
              {{ zoomPercent }}%
            </button>
            <button
              type="button"
              class="lightbox-action icon-only"
              :title="t('attachments.zoomIn')"
              :aria-label="t('attachments.zoomIn')"
              :disabled="!activeImage?.url || scale >= maxScale - 1e-6"
              @click="zoomBy(ZOOM_STEP)"
            >
              <n-icon :size="16"><AddOutline /></n-icon>
            </button>
            <button
              type="button"
              class="lightbox-action"
              :title="t('attachments.zoomFit')"
              :aria-label="t('attachments.zoomFit')"
              :disabled="!activeImage?.url"
              @click="fitToWindow"
            >
              <n-icon :size="15"><ExpandOutline /></n-icon>
              <span>{{ t('attachments.zoomFit') }}</span>
            </button>
          </div>
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
            :disabled="!systemOpenable || actionBusy"
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

        <div
          ref="stageRef"
          class="lightbox-stage"
          :class="{ 'is-pannable': pannable, 'is-dragging': dragging }"
          @click="handleStageClick"
          @wheel.prevent="handleWheel"
          @pointerdown="handlePointerDown"
          @pointermove="handlePointerMove"
          @pointerup="handlePointerUp"
          @pointercancel="handlePointerUp"
        >
          <button
            v-if="images.length > 1"
            type="button"
            class="lightbox-nav prev"
            :aria-label="t('attachments.previousImage')"
            @pointerdown.stop
            @click.stop="step(-1)"
          >‹</button>

          <img
            v-if="activeImage?.url"
            ref="imageRef"
            class="lightbox-image"
            :class="{ 'is-ready': imageReady }"
            :style="imageStyle"
            :src="activeImage.url"
            :alt="activeImage.name"
            draggable="false"
            @load="handleImageLoad"
            @click.stop
            @dblclick.stop.prevent="toggleFitActual"
          />
          <p v-else class="lightbox-empty">{{ t('attachments.imageUnavailable') }}</p>

          <button
            v-if="images.length > 1"
            type="button"
            class="lightbox-nav next"
            :aria-label="t('attachments.nextImage')"
            @pointerdown.stop
            @click.stop="step(1)"
          >›</button>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { NIcon } from 'naive-ui'
import { AddOutline, CloseOutline, CopyOutline, ExpandOutline, OpenOutline, RemoveOutline } from '@vicons/ionicons5'
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
// Images coming from the markdown body only carry a URL; there is no file to
// hand to the system viewer, so that action is disabled instead of failing.
const systemOpenable = computed(() => Boolean(activeImage.value?.path || activeImage.value?.attachmentId))
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

// --- Zoom / pan -----------------------------------------------------------
// The image is laid out at `natural size × scale` and centered by the flex
// stage; panning is a translate on top of that center. `scale` is absolute
// (1 === 100% of the natural size), so `fitScale` is whatever makes the whole
// image fit inside the stage.
const ZOOM_STEP = 1.25
const MIN_FIT_FACTOR = 0.25
const MAX_FIT_FACTOR = 8

const stageRef = ref<HTMLElement | null>(null)
const imageRef = ref<HTMLImageElement | null>(null)
const stageSize = ref({ width: 0, height: 0 })
const naturalWidth = ref(0)
const naturalHeight = ref(0)
const imageReady = ref(false)
const scale = ref(1)
const pan = ref({ x: 0, y: 0 })
const dragging = ref(false)
const atFit = ref(true)
let dragState: { pointerId: number; startX: number; startY: number; panX: number; panY: number } | null = null
let suppressStageClick = false

const fitScale = computed(() => {
  if (!naturalWidth.value || !naturalHeight.value) return 1
  const { width, height } = stageSize.value
  if (!width || !height) return 1
  // "Fit" never upscales: an image smaller than the stage stays at 100% rather
  // than being blown up into a blurry mess.
  return Math.min(1, width / naturalWidth.value, height / naturalHeight.value)
})
const minScale = computed(() => fitScale.value * MIN_FIT_FACTOR)
const maxScale = computed(() => fitScale.value * MAX_FIT_FACTOR)
const zoomPercent = computed(() => Math.round(scale.value * 100))
const isFitView = computed(() => (
  Math.abs(scale.value - fitScale.value) < 1e-4
  && Math.abs(pan.value.x) < 0.5
  && Math.abs(pan.value.y) < 0.5
))
const pannable = computed(() => {
  const { width, height } = stageSize.value
  if (!width || !height || !naturalWidth.value || !naturalHeight.value) return false
  return naturalWidth.value * scale.value > width + 0.5
    || naturalHeight.value * scale.value > height + 0.5
})
const imageStyle = computed(() => {
  if (!naturalWidth.value || !naturalHeight.value) return undefined
  return {
    width: `${naturalWidth.value * scale.value}px`,
    height: `${naturalHeight.value * scale.value}px`,
    transform: `translate3d(${pan.value.x}px, ${pan.value.y}px, 0)`,
  }
})

function clampScale(value: number): number {
  return Math.min(Math.max(value, minScale.value), maxScale.value)
}

/** Re-reads the stage box; returns true when the size actually changed. */
function refreshStageSize(): boolean {
  const el = stageRef.value
  if (!el) return false
  const { clientWidth: width, clientHeight: height } = el
  if (!width || !height) return false
  if (width === stageSize.value.width && height === stageSize.value.height) return false
  stageSize.value = { width, height }
  return true
}

/** Keeps the image inside the stage: pannable only while it overflows an axis. */
function clampPanning(): void {
  const { width, height } = stageSize.value
  if (!width || !height) return
  const limitX = Math.max(0, (naturalWidth.value * scale.value - width) / 2)
  const limitY = Math.max(0, (naturalHeight.value * scale.value - height) / 2)
  pan.value = {
    x: Math.min(limitX, Math.max(-limitX, pan.value.x)),
    y: Math.min(limitY, Math.max(-limitY, pan.value.y)),
  }
}

function applyFit(): void {
  scale.value = clampScale(fitScale.value)
  pan.value = { x: 0, y: 0 }
  atFit.value = true
}

/** Resets zoom + pan and re-measures; the single entry point for open/switch. */
function initializeView(): void {
  imageReady.value = false
  naturalWidth.value = 0
  naturalHeight.value = 0
  dragging.value = false
  dragState = null
  suppressStageClick = false
  scale.value = 1
  pan.value = { x: 0, y: 0 }
  atFit.value = true
  void nextTick(() => {
    refreshStageSize()
    // A cached image can already be decoded before `load` is observable.
    syncImageSize()
    if (!imageReady.value) scale.value = clampScale(fitScale.value)
  })
}

function syncImageSize(): void {
  const el = imageRef.value
  if (!el) return
  const { naturalWidth: width, naturalHeight: height } = el
  if (!width || !height) return
  const changed = width !== naturalWidth.value || height !== naturalHeight.value
  naturalWidth.value = width
  naturalHeight.value = height
  imageReady.value = true
  if (changed) {
    refreshStageSize()
    applyFit()
  }
}

function handleImageLoad(): void {
  syncImageSize()
}

function handleResize(): void {
  if (!refreshStageSize()) return
  if (atFit.value) applyFit()
  else clampPanning()
}

function stageCenter(): { x: number; y: number } {
  const rect = stageRef.value?.getBoundingClientRect()
  if (!rect) return { x: 0, y: 0 }
  return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 }
}

/**
 * Zooms to an absolute scale while keeping the point under (clientX, clientY)
 * fixed. The offset of the pointer from the stage center is converted into
 * image-local units before the scale changes, then projected back after it.
 */
function zoomTo(target: number, clientX?: number, clientY?: number): void {
  if (!naturalWidth.value || !naturalHeight.value) return
  const next = clampScale(target)
  if (Math.abs(next - scale.value) < 1e-6) return
  const rect = stageRef.value?.getBoundingClientRect()
  if (rect && rect.width && rect.height && clientX !== undefined && clientY !== undefined) {
    const anchorX = clientX - (rect.left + rect.width / 2)
    const anchorY = clientY - (rect.top + rect.height / 2)
    const imageX = (anchorX - pan.value.x) / scale.value
    const imageY = (anchorY - pan.value.y) / scale.value
    scale.value = next
    pan.value = { x: anchorX - imageX * next, y: anchorY - imageY * next }
  } else {
    scale.value = next
  }
  atFit.value = false
  clampPanning()
}

function zoomBy(factor: number): void {
  const center = stageCenter()
  zoomTo(scale.value * factor, center.x, center.y)
}

function zoomToActualSize(): void {
  const center = stageCenter()
  zoomTo(1, center.x, center.y)
}

function fitToWindow(): void {
  applyFit()
  clampPanning()
}

function toggleFitActual(): void {
  if (isFitView.value) zoomToActualSize()
  else fitToWindow()
}

function handleWheel(event: WheelEvent): void {
  if (!activeImage.value?.url) return
  // Exponential response keeps each notch a constant relative change.
  const factor = Math.exp(-event.deltaY * 0.0015)
  zoomTo(scale.value * factor, event.clientX, event.clientY)
}

function handleStageClick(event: MouseEvent): void {
  if (event.target !== event.currentTarget) return
  // A pan ends with a click on the stage; that must not close the viewer.
  if (suppressStageClick) {
    suppressStageClick = false
    return
  }
  close()
}

function handlePointerDown(event: PointerEvent): void {
  suppressStageClick = false
  if (event.button !== 0 || !pannable.value) return
  dragState = {
    pointerId: event.pointerId,
    startX: event.clientX,
    startY: event.clientY,
    panX: pan.value.x,
    panY: pan.value.y,
  }
  dragging.value = true
  try {
    (event.currentTarget as HTMLElement | null)?.setPointerCapture(event.pointerId)
  } catch {
    // Pointer capture is best-effort; dragging still works without it.
  }
}

function handlePointerMove(event: PointerEvent): void {
  if (!dragState || event.pointerId !== dragState.pointerId) return
  const deltaX = event.clientX - dragState.startX
  const deltaY = event.clientY - dragState.startY
  if (Math.abs(deltaX) > 3 || Math.abs(deltaY) > 3) suppressStageClick = true
  pan.value = { x: dragState.panX + deltaX, y: dragState.panY + deltaY }
  atFit.value = false
  clampPanning()
}

function handlePointerUp(event: PointerEvent): void {
  if (!dragState || event.pointerId !== dragState.pointerId) return
  try {
    (event.currentTarget as HTMLElement | null)?.releasePointerCapture(dragState.pointerId)
  } catch {
    // Already released or never captured.
  }
  dragState = null
  dragging.value = false
}

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
  if (event.key === 'Escape') {
    close()
    return
  }
  // Never hijack typing in a form control that happens to be on the page.
  const target = event.target as HTMLElement | null
  if (target && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))) return
  if (event.key === 'ArrowLeft') step(-1)
  else if (event.key === 'ArrowRight') step(1)
  else if (event.key === '+' || event.key === '=') {
    event.preventDefault()
    zoomBy(ZOOM_STEP)
  } else if (event.key === '-' || event.key === '_') {
    event.preventDefault()
    zoomBy(1 / ZOOM_STEP)
  } else if (event.key === '0') {
    event.preventDefault()
    fitToWindow()
  }
}

// Opening, switching image and reopening all restart from the fit view; the
// zoom state is never carried across images.
watch(() => props.open, (open) => {
  resetActionState()
  if (typeof document === 'undefined') return
  document.documentElement.style.overflow = open ? 'hidden' : ''
  initializeView()
})

watch(() => activeImage.value?.url, () => {
  initializeView()
})

onMounted(() => {
  // Mounting already-open (e.g. a deep-linked preview) must lock scrolling the
  // same way opening later does; the watcher only fires on changes.
  if (!props.open) return
  if (typeof document !== 'undefined') document.documentElement.style.overflow = 'hidden'
  initializeView()
})

onBeforeUnmount(() => {
  resetActionState()
  if (typeof window !== 'undefined') {
    window.removeEventListener('keydown', handleKeydown)
    window.removeEventListener('resize', handleResize)
  }
  if (typeof document !== 'undefined') document.documentElement.style.overflow = ''
})

if (typeof window !== 'undefined') {
  window.addEventListener('keydown', handleKeydown)
  window.addEventListener('resize', handleResize)
}
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

/* Compact grouped zoom cluster: − / percent / + / fit. */
.lightbox-zoom {
  display: inline-flex;
  flex: none;
  align-items: center;
  gap: 2px;
  padding: 2px;
  border-radius: var(--app-radius-pill);
  background: rgba(255, 255, 255, 0.08);
}

.lightbox-zoom .lightbox-action {
  border-color: transparent;
  background: transparent;
}

.lightbox-zoom-value {
  min-width: 54px;
  justify-content: center;
  font-variant-numeric: tabular-nums;
}

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

/*
 * Flex centering of an explicitly sized image. `.lightbox-image` keeps its
 * computed width/height (`flex: none` stops the flex item from shrinking back
 * to the stage), so `max-height: 100%` is not needed to fit it; the fit scale
 * is computed from the measured image and stage boxes instead, which is what
 * fixes the tall/oversized image overflowing and being cropped.
 */
.lightbox-stage {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 0;
  overflow: hidden;
  touch-action: none;
}

.lightbox-stage.is-pannable { cursor: grab; }
.lightbox-stage.is-dragging { cursor: grabbing; }

.lightbox-image {
  display: block;
  flex: none;
  /* The global tailwind reset clamps every image to `max-width: 100%`; the
     lightbox sizes the image itself, so that clamp has to be lifted or zooming
     in would be capped at the stage width. */
  max-width: none;
  max-height: none;
  visibility: hidden;
  border-radius: var(--app-radius-md);
  box-shadow: 0 18px 60px rgba(0, 0, 0, 0.45);
  object-fit: contain;
  user-select: none;
  -webkit-user-drag: none;
  -webkit-user-select: none;
  will-change: transform;
}

.lightbox-image.is-ready { visibility: visible; }

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
