<template>
  <Teleport to="body">
    <aside
      v-if="visible"
      ref="panelRef"
      class="browser-panel"
      :class="{ minimized, dragging }"
      :style="panelStyle"
    >
      <div class="page-capsule-stack">
      <div
        v-for="(target, index) in browserTargets"
        :key="target.pageId"
        class="page-capsule"
        :class="{ active: target.pageId === activePageId }"
        :style="{ zIndex: index + 1 }"
        @pointerdown="target.pageId === activePageId && beginPanelDrag($event)"
      >
        <button class="capsule-select" type="button" @click="activateTarget(target)">
          <span
            class="live-dot"
            :class="target.pageId === activePageId ? connectionStatus : 'parked'"
          ></span>
          <span class="capsule-copy">
            <strong>{{ target.title || target.url || t('browser.panelTitle') }}</strong>
            <small v-if="target.pageId === activePageId && agentOperation">{{ agentOperation }}</small>
          </span>
        </button>
        <div class="capsule-actions">
          <span v-if="target.pageId === activePageId" class="capsule-grip" aria-hidden="true">⠿</span>
          <button v-if="target.pageId === activePageId" type="button" @click="minimized = !minimized">
            {{ minimized ? t('browser.expand') : t('browser.minimize') }}
          </button>
          <button
            type="button"
            :aria-label="t('common.close')"
            :disabled="closingPageIds.has(target.pageId)"
            @click.stop="closeTarget(target)"
          >×</button>
        </div>
      </div>
      </div>

      <div v-if="!minimized && currentTarget" class="browser-window">
        <div class="browser-toolbar">
        <button type="button" :aria-label="t('browser.back')" @click="send({ type: 'back' })">←</button>
        <button type="button" :aria-label="t('browser.forward')" @click="send({ type: 'forward' })">→</button>
        <button type="button" :aria-label="t('browser.reload')" @click="send({ type: 'reload' })">↻</button>
        <form class="address-form" @submit.prevent="navigate">
          <input v-model="address" :aria-label="t('browser.address')" spellcheck="false" />
        </form>
        <button
          class="control-toggle"
          :class="{ active: interactive }"
          type="button"
          @click="interactive = !interactive"
        >
          {{ interactive ? t('browser.releaseControl') : t('browser.takeControl') }}
        </button>
        </div>

        <div
          class="browser-viewport"
          :class="{ interactive }"
          :style="{ aspectRatio: viewportAspectRatio }"
          @wheel.prevent="handleWheel"
        >
          <canvas
            ref="canvasRef"
            :tabindex="interactive ? 0 : -1"
            @pointerdown.prevent="handlePointer($event, 'down')"
            @pointerup.prevent="handlePointer($event, 'up')"
            @pointercancel="handlePointer($event, 'up')"
            @pointermove="handlePointer($event, 'move')"
            @contextmenu.prevent
            @keydown.prevent="handleKey"
            @compositionend="handleComposition"
          ></canvas>
          <div v-if="connectionStatus !== 'connected'" class="viewport-status">
            {{ statusText }}
          </div>
          <div v-else-if="!interactive" class="watching-badge">{{ t('browser.agentControl') }}</div>
        </div>
      </div>
    </aside>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from '@/composables/useI18n'
import { backendUrl } from '@/api/backendUrl'
import { useRuntimeStore } from '@/stores/runtime'

interface BrowserTarget {
  viewId: string
  pageId: string
  url: string
  title: string
}

const runtimeStore = useRuntimeStore()
const { t } = useI18n()
const visible = ref(false)
const minimized = ref(false)
const interactive = ref(false)
const connectionStatus = ref<'connecting' | 'connected' | 'error' | 'closed'>('closed')
const address = ref('')
const title = ref('')
const agentOperation = ref('')
const browserTargets = ref<BrowserTarget[]>([])
const closingPageIds = ref(new Set<string>())
const closedPageIds = ref(new Set<string>())
const activePageId = ref('')
const panelRef = ref<HTMLElement | null>(null)
const canvasRef = ref<HTMLCanvasElement | null>(null)
const sourceWidth = ref(1440)
const sourceHeight = ref(900)
const panelPosition = ref<{ x: number; y: number } | null>(null)
const dragging = ref(false)
let socket: WebSocket | null = null
let connectionGeneration = 0
let pendingFrameMetadata: Record<string, any> | null = null
let dragState: {
  pointerId: number
  offsetX: number
  offsetY: number
  originX: number
  originY: number
  captureTarget: HTMLElement
} | null = null
let suppressCapsuleClick = false
let activeCanvasPointer: number | null = null

const panelStyle = computed(() => panelPosition.value
  ? { left: `${panelPosition.value.x}px`, top: `${panelPosition.value.y}px` }
  : { right: '18px', top: '76px' })

const viewportAspectRatio = computed(() => (
  `${Math.max(sourceWidth.value, 1)} / ${Math.max(sourceHeight.value, 1)}`
))

const currentTarget = computed(() => (
  browserTargets.value.find((target) => target.pageId === activePageId.value) || null
))

const latestBrowserActivity = computed(() => {
  for (let index = runtimeStore.tools.length - 1; index >= 0; index -= 1) {
    const activity = runtimeStore.tools[index]
    if (activity.toolName.startsWith('browser_')) return activity
  }
  return null
})

const activeBrowserScope = computed(() => String(runtimeStore.activeConversationScope || '').trim())

const statusText = computed(() => {
  if (connectionStatus.value === 'error') return t('browser.connectionFailed')
  if (connectionStatus.value === 'closed') return t('browser.connectionClosed')
  return t('browser.connecting')
})

watch(latestBrowserActivity, (activity) => {
  if (!activity) return
  agentOperation.value = t('browser.agentOperation', { tool: activity.toolName })
  if (activity.status === 'started') {
    if (activity.toolName === 'browser_open') {
      visible.value = true
      minimized.value = false
      connectionStatus.value = 'connecting'
      void nextTick(clampPanelPosition)
      const requestedUrl = String(toolArguments(activity.payload).url || '').trim()
      if (requestedUrl) address.value = requestedUrl
    }
    return
  }
  if (activity.status === 'failed' || activity.status === 'cancelled') {
    if (activity.toolName === 'browser_open') connectionStatus.value = 'error'
    return
  }
  if (activity.status !== 'completed' && activity.status !== 'observed') return
  const output = browserOutput(activity.payload)
  const action = String(output?.browser_view_action || '').trim()
  const closedPageId = String(output?.closed_page_id || '').trim()
  if (closedPageId) markTargetClosed(closedPageId)
  if (action === 'close') {
    browserTargets.value = []
    activePageId.value = ''
    closePanel()
    return
  }
  if (Array.isArray(output?.tabs)) {
    const tabs = output.tabs
    synchronizeTargets(String(output?.browser_view_id || '').trim(), tabs)
    const requestedActivePage = String(output?.active_page_id || '').trim()
    if (requestedActivePage) activePageId.value = requestedActivePage
    visible.value = browserTargets.value.length > 0
    return
  }
  const viewId = String(output?.browser_view_id || '').trim()
  const pageId = String(output?.page_id || '').trim()
  if (!viewId || !pageId || closedPageIds.value.has(pageId)) return
  const target = {
    viewId,
    pageId,
    url: String(output?.url || ''),
    title: String(output?.title || ''),
  }
  upsertTarget(target)
  activePageId.value = target.pageId
  visible.value = true
  minimized.value = false
  void nextTick(clampPanelPosition)
}, { deep: true, immediate: true })

watch(activeBrowserScope, (scope, previousScope) => {
  if (!scope || scope === previousScope) return
  browserTargets.value = []
  activePageId.value = ''
  panelPosition.value = null
  closedPageIds.value = new Set()
  closePanel()
}, { immediate: true })

watch(minimized, () => {
  void nextTick(clampPanelPosition)
})

watch(currentTarget, (target, previous) => {
  if (!target) {
    socket?.close()
    socket = null
    return
  }
  address.value = target.url
  title.value = target.title
  const pageChanged = !previous
    || target.viewId !== previous.viewId
    || target.pageId !== previous.pageId
  if (pageChanged) {
    sourceWidth.value = 1440
    sourceHeight.value = 900
  }
  if (pageChanged || !socket) {
    void connect(target)
  }
})

watch(() => browserTargets.value.length, () => {
  void nextTick(clampPanelPosition)
})

async function connect(target: BrowserTarget) {
  const generation = ++connectionGeneration
  socket?.close()
  connectionStatus.value = 'connecting'
  const url = new URL(await backendUrl(
    `/api/browser/views/${encodeURIComponent(target.viewId)}/pages/${encodeURIComponent(target.pageId)}`,
  ), window.location.href)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  if (generation !== connectionGeneration) return
  const nextSocket = new WebSocket(url)
  nextSocket.binaryType = 'blob'
  socket = nextSocket
  nextSocket.addEventListener('open', () => {
    if (socket === nextSocket) connectionStatus.value = 'connected'
  })
  nextSocket.addEventListener('message', (event) => {
    if (socket !== nextSocket) return
    connectionStatus.value = 'connected'
    if (event.data instanceof Blob) {
      const metadata = pendingFrameMetadata || {}
      pendingFrameMetadata = null
      void renderFrame(event.data, metadata)
      return
    }
    const payload = JSON.parse(String(event.data || '{}'))
    if (payload.type === 'error') {
      connectionStatus.value = 'error'
      return
    }
    if (payload.type === 'closed') {
      markTargetClosed(target.pageId)
      if (!browserTargets.value.length) closePanel()
      return
    }
    if (payload.type === 'frame_metadata') pendingFrameMetadata = payload
  })
  nextSocket.addEventListener('error', () => {
    if (socket === nextSocket) connectionStatus.value = 'error'
  })
  nextSocket.addEventListener('close', () => {
    if (socket === nextSocket && connectionStatus.value !== 'error') connectionStatus.value = 'closed'
  })
}

async function renderFrame(frame: Blob, payload: Record<string, any>) {
  const image = new Image()
  const objectUrl = URL.createObjectURL(frame)
  image.src = objectUrl
  try {
    await image.decode()
  } finally {
    URL.revokeObjectURL(objectUrl)
  }
  sourceWidth.value = Number(payload.metadata?.deviceWidth || image.naturalWidth || 1440)
  sourceHeight.value = Number(payload.metadata?.deviceHeight || image.naturalHeight || 900)
  address.value = String(payload.url || address.value)
  title.value = String(payload.title || title.value)
  const target = currentTarget.value
  if (target && (target.url !== address.value || target.title !== title.value)) {
    upsertTarget({ ...target, url: address.value, title: title.value }, false)
  }
  await nextTick()
  const canvas = canvasRef.value
  if (!canvas) return
  canvas.width = image.naturalWidth
  canvas.height = image.naturalHeight
  canvas.getContext('2d')?.drawImage(image, 0, 0)
  connectionStatus.value = 'connected'
}

function send(payload: Record<string, any>) {
  if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(payload))
}

function navigate() {
  const url = address.value.trim()
  if (url) send({ type: 'navigate', url })
}

function handlePointer(event: PointerEvent, action: 'down' | 'up' | 'move') {
  if (!interactive.value) return
  const canvas = canvasRef.value
  if (!canvas) return
  if (action === 'down') {
    activeCanvasPointer = event.pointerId
    canvas.setPointerCapture(event.pointerId)
    canvas.focus({ preventScroll: true })
  }
  if (action === 'move' && activeCanvasPointer !== event.pointerId) return
  if (action === 'up' && activeCanvasPointer !== event.pointerId) return
  const bounds = canvas.getBoundingClientRect()
  send({
    type: 'mouse',
    action,
    button: mouseButton(event.button),
    x: ((event.clientX - bounds.left) / bounds.width) * sourceWidth.value,
    y: ((event.clientY - bounds.top) / bounds.height) * sourceHeight.value,
  })
  if (action === 'up') {
    if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId)
    activeCanvasPointer = null
  }
}

function handleWheel(event: WheelEvent) {
  if (!interactive.value) return
  send({ type: 'wheel', delta_x: event.deltaX, delta_y: event.deltaY })
}

function handleKey(event: KeyboardEvent) {
  if (!interactive.value || event.isComposing) return
  if (event.key.length === 1 && !event.metaKey && !event.ctrlKey && !event.altKey) {
    send({ type: 'text', text: event.key })
    return
  }
  send({ type: 'key', key: keyboardShortcut(event) })
}

function handleComposition(event: CompositionEvent) {
  if (interactive.value && event.data) send({ type: 'text', text: event.data })
}

function keyboardShortcut(event: KeyboardEvent): string {
  return [event.metaKey ? 'Meta' : '', event.ctrlKey ? 'Control' : '', event.altKey ? 'Alt' : '', event.shiftKey ? 'Shift' : '', event.key]
    .filter(Boolean)
    .join('+')
}

function mouseButton(button: number): 'left' | 'middle' | 'right' {
  if (button === 1) return 'middle'
  if (button === 2) return 'right'
  return 'left'
}

function browserOutput(payload: Record<string, any>): Record<string, any> | null {
  const candidates = [
    payload.output,
    payload.result?.output,
    payload.result,
    payload.observation?.output,
    payload.observation,
  ]
  return candidates.find((value) => value && typeof value === 'object') || null
}

function toolArguments(payload: Record<string, any>): Record<string, any> {
  const value = payload.arguments || payload.input || payload.tool_input
  return value && typeof value === 'object' ? value : {}
}

function upsertTarget(target: BrowserTarget, moveToFront = true) {
  if (closedPageIds.value.has(target.pageId)) return
  const remaining = browserTargets.value.filter((item) => item.pageId !== target.pageId)
  const previous = browserTargets.value.find((item) => item.pageId === target.pageId)
  const merged = { ...previous, ...target }
  if (moveToFront) {
    browserTargets.value = [...remaining, merged]
    return
  }
  const previousIndex = browserTargets.value.findIndex((item) => item.pageId === target.pageId)
  if (previousIndex < 0) {
    browserTargets.value = [...browserTargets.value, merged]
    return
  }
  const updated = [...browserTargets.value]
  updated[previousIndex] = merged
  browserTargets.value = updated
}

function synchronizeTargets(viewId: string, tabs: Array<Record<string, any>>) {
  if (!viewId) return
  const existing = new Map(browserTargets.value.map((target) => [target.pageId, target]))
  browserTargets.value = tabs
    .map((tab) => {
      const pageId = String(tab.page_id || '').trim()
      if (!pageId || closedPageIds.value.has(pageId)) return null
      return {
        viewId,
        pageId,
        url: String(tab.url || existing.get(pageId)?.url || ''),
        title: String(tab.title || existing.get(pageId)?.title || ''),
      }
    })
    .filter((target): target is BrowserTarget => target !== null)
  if (!browserTargets.value.some((target) => target.pageId === activePageId.value)) {
    activePageId.value = browserTargets.value[browserTargets.value.length - 1]?.pageId || ''
  }
}

function removeTarget(pageId: string) {
  if (!pageId) return
  browserTargets.value = browserTargets.value.filter((target) => target.pageId !== pageId)
  if (activePageId.value === pageId) {
    activePageId.value = browserTargets.value[browserTargets.value.length - 1]?.pageId || ''
  }
}

function markTargetClosed(pageId: string) {
  if (!pageId) return
  closedPageIds.value = new Set([...closedPageIds.value, pageId])
  removeTarget(pageId)
}

function activateTarget(target: BrowserTarget) {
  if (suppressCapsuleClick) return
  upsertTarget(target)
  activePageId.value = target.pageId
  visible.value = true
  minimized.value = false
}

async function closeTarget(target: BrowserTarget) {
  if (closingPageIds.value.has(target.pageId)) return
  closingPageIds.value = new Set([...closingPageIds.value, target.pageId])
  try {
    const response = await fetch(await backendUrl(
      `/api/browser/views/${encodeURIComponent(target.viewId)}/pages/${encodeURIComponent(target.pageId)}`,
    ), { method: 'DELETE' })
    const result = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(String(result.detail || `HTTP ${response.status}`))
    markTargetClosed(target.pageId)
    const nextPageId = String(result.page_id || '').trim()
    if (nextPageId && browserTargets.value.some((item) => item.pageId === nextPageId)) {
      activePageId.value = nextPageId
    }
    if (!browserTargets.value.length) closePanel()
  } catch (error) {
    console.error('Failed to close browser page', error)
    if (target.pageId === activePageId.value) connectionStatus.value = 'error'
  } finally {
    const remaining = new Set(closingPageIds.value)
    remaining.delete(target.pageId)
    closingPageIds.value = remaining
  }
}

function beginPanelDrag(event: PointerEvent) {
  if (event.button !== 0) return
  const target = event.target as HTMLElement | null
  if (target?.closest('.capsule-actions button')) return
  const panel = panelRef.value
  if (!panel) return
  event.preventDefault()
  const captureTarget = event.currentTarget as HTMLElement
  captureTarget.setPointerCapture(event.pointerId)
  const bounds = panel.getBoundingClientRect()
  dragState = {
    pointerId: event.pointerId,
    offsetX: event.clientX - bounds.left,
    offsetY: event.clientY - bounds.top,
    originX: event.clientX,
    originY: event.clientY,
    captureTarget,
  }
  dragging.value = true
  window.addEventListener('pointermove', movePanel)
  window.addEventListener('pointerup', endPanelDrag)
  window.addEventListener('pointercancel', endPanelDrag)
}

function movePanel(event: PointerEvent) {
  if (!dragState || event.pointerId !== dragState.pointerId) return
  const panel = panelRef.value
  if (!panel) return
  const bounds = panel.getBoundingClientRect()
  panelPosition.value = constrainedPosition(
    event.clientX - dragState.offsetX,
    event.clientY - dragState.offsetY,
    bounds.width,
    bounds.height,
  )
}

function endPanelDrag(event: PointerEvent) {
  if (!dragState || event.pointerId !== dragState.pointerId) return
  const moved = Math.hypot(
    event.clientX - dragState.originX,
    event.clientY - dragState.originY,
  ) > 4
  if (dragState.captureTarget.hasPointerCapture(event.pointerId)) {
    dragState.captureTarget.releasePointerCapture(event.pointerId)
  }
  dragState = null
  dragging.value = false
  window.removeEventListener('pointermove', movePanel)
  window.removeEventListener('pointerup', endPanelDrag)
  window.removeEventListener('pointercancel', endPanelDrag)
  if (moved) {
    suppressCapsuleClick = true
    window.setTimeout(() => { suppressCapsuleClick = false }, 120)
  }
}

function constrainedPosition(x: number, y: number, width: number, height: number) {
  const margin = 10
  return {
    x: Math.min(Math.max(x, margin), Math.max(margin, window.innerWidth - width - margin)),
    y: Math.min(Math.max(y, margin), Math.max(margin, window.innerHeight - height - margin)),
  }
}

function clampPanelPosition() {
  const panel = panelRef.value
  if (!panel) return
  const bounds = panel.getBoundingClientRect()
  const current = panelPosition.value
  panelPosition.value = constrainedPosition(
    current?.x ?? window.innerWidth - bounds.width - 18,
    current?.y ?? 76,
    bounds.width,
    bounds.height,
  )
}

function closePanel() {
  visible.value = false
  interactive.value = false
  socket?.close()
  socket = null
  pendingFrameMetadata = null
  agentOperation.value = ''
}

onBeforeUnmount(() => {
  connectionGeneration += 1
  socket?.close()
  window.removeEventListener('resize', clampPanelPosition)
  window.removeEventListener('pointermove', movePanel)
  window.removeEventListener('pointerup', endPanelDrag)
  window.removeEventListener('pointercancel', endPanelDrag)
})

onMounted(() => {
  window.addEventListener('resize', clampPanelPosition)
})
</script>

<style scoped>
.browser-panel { position: fixed; z-index: 35; width: clamp(360px, 30vw, 460px); min-width: 0; display: flex; flex-direction: column; overflow: visible; transition: width .26s cubic-bezier(.16, 1, .3, 1); }
.browser-panel.minimized { width: min(340px, calc(100vw - 20px)); }
.browser-panel.dragging { transition: none; user-select: none; }
.page-capsule-stack { display: flex; max-height: 176px; flex-direction: column; align-items: flex-end; gap: 5px; padding: 8px 8px 2px; overflow-y: auto; scrollbar-width: none; }
.page-capsule-stack::-webkit-scrollbar { display: none; }
.page-capsule { width: min(100%, 360px); min-height: 46px; display: flex; align-items: center; border: 1px solid var(--app-divider); border-radius: 999px; background: color-mix(in srgb, var(--app-surface-elevated) 94%, transparent); backdrop-filter: blur(18px); transition: width .2s ease, transform .2s ease, border-color .2s ease; }
.page-capsule.active { width: 100%; border-color: var(--app-border-focus); cursor: grab; touch-action: none; user-select: none; }
.browser-panel.dragging .page-capsule.active { cursor: grabbing; }
.capsule-select { min-width: 0; flex: 1; display: flex; align-items: center; gap: 9px; padding: 9px 8px 9px 13px; text-align: left; }
.capsule-copy { min-width: 0; display: grid; gap: 1px; }
.capsule-copy strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; }
.capsule-copy small { overflow: hidden; color: var(--app-text-muted); font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.capsule-actions { flex: 0 0 auto; display: flex; align-items: center; gap: 1px; padding-right: 7px; }
.capsule-actions button { padding: 5px 7px; font-size: 11px; }
.capsule-grip { padding: 6px 4px; color: var(--app-text-muted); cursor: grab; touch-action: none; }
.browser-panel.dragging .capsule-grip { cursor: grabbing; }
.live-dot { width: 8px; height: 8px; flex: 0 0 auto; border-radius: 50%; background: var(--app-text-muted); }
.live-dot.connected { background: var(--app-success); box-shadow: 0 0 0 5px color-mix(in srgb, var(--app-success) 14%, transparent); }
.live-dot.connecting { animation: browser-pulse 1s ease-in-out infinite; }
.live-dot.error { background: var(--app-error); }
.live-dot.parked { opacity: .5; }
button { border: 0; border-radius: 10px; padding: 7px 9px; color: var(--app-text); background: transparent; cursor: pointer; }
button:hover { background: var(--app-surface-muted); }
.browser-window { margin-top: 5px; overflow: hidden; border: 1px solid var(--app-divider); border-radius: 20px; background: var(--app-surface-elevated); box-shadow: 0 18px 50px rgba(0, 0, 0, .16); }
.browser-toolbar { min-height: 40px; display: flex; align-items: center; gap: 3px; margin: 7px; padding: 4px; border: 1px solid var(--app-divider); border-radius: 999px; background: var(--app-surface-muted); }
.browser-toolbar > button { padding: 5px 7px; }
.address-form { flex: 1; }
.address-form input { width: 100%; height: 28px; padding: 0 9px; border: 1px solid var(--app-divider); border-radius: 999px; outline: 0; color: var(--app-text); background: var(--app-surface-elevated); font-size: 11px; }
.control-toggle { white-space: nowrap; border: 1px solid var(--app-divider); font-size: 10px; }
.control-toggle.active { color: var(--app-surface); background: var(--app-text); }
.browser-viewport { position: relative; width: calc(100% - 14px); min-height: 0; display: grid; place-items: center; margin: 0 7px 7px; overflow: hidden; border: 1px solid var(--app-divider); border-radius: 14px; background: var(--app-surface-muted); }
.browser-viewport canvas { display: block; width: 100%; height: 100%; cursor: default; touch-action: none; }
.browser-viewport.interactive canvas { cursor: crosshair; }
.viewport-status { position: absolute; padding: 10px 14px; border-radius: 12px; color: white; background: rgba(0, 0, 0, .68); backdrop-filter: blur(12px); }
.watching-badge { position: absolute; right: 12px; bottom: 12px; padding: 6px 10px; border-radius: 999px; color: white; background: rgba(0, 0, 0, .58); font-size: 11px; backdrop-filter: blur(10px); }
@keyframes browser-pulse { 50% { opacity: .35; transform: scale(.75); } }
@media (max-width: 560px) { .browser-panel { width: calc(100vw - 20px); } .control-toggle { padding-inline: 6px; } }
</style>
