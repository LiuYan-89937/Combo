import { computed, onBeforeUnmount, onMounted, ref, type Ref } from 'vue'

// Shared by browser and native CU floating capsules.
export function useFloatingCapsule(panelRef: Ref<HTMLElement | null>, initial = { right: 18, top: 76 }) {
const panelPosition = ref<{ x: number; y: number } | null>(null)
const dragging = ref(false)
let suppressionTimer: number | undefined
let dragState: {
  pointerId: number
  offsetX: number
  offsetY: number
  originX: number
  originY: number
  captureTarget: HTMLElement
} | null = null
let suppressCapsuleClick = false
const panelStyle = computed(() => panelPosition.value
  ? { left: `${panelPosition.value.x}px`, top: `${panelPosition.value.y}px` }
  : { right: `${initial.right}px`, top: `${initial.top}px` })
function beginPanelDrag(event: PointerEvent) {
  if (event.button !== 0) return
  const target = event.target as HTMLElement | null
  if (target?.closest('.capsule-actions button')) return
  const panel = panelRef.value
  if (!panel) return
  event.preventDefault()
  const captureTarget = event.currentTarget as HTMLElement
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
    clearTimeout(suppressionTimer)
    suppressionTimer = window.setTimeout(() => { suppressCapsuleClick = false }, 120)
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
    current?.x ?? window.innerWidth - bounds.width - initial.right,
    current?.y ?? initial.top,
    bounds.width,
    bounds.height,
  )
}


onMounted(() => window.addEventListener('resize', clampPanelPosition))
onBeforeUnmount(() => {
  if (dragState?.captureTarget.hasPointerCapture(dragState.pointerId)) {
    dragState.captureTarget.releasePointerCapture(dragState.pointerId)
  }
  clearTimeout(suppressionTimer)
  window.removeEventListener('resize', clampPanelPosition)
  window.removeEventListener('pointermove', movePanel)
  window.removeEventListener('pointerup', endPanelDrag)
  window.removeEventListener('pointercancel', endPanelDrag)
})
return { panelPosition, panelStyle, dragging, beginPanelDrag, clampPanelPosition,
  shouldSuppressClick: () => suppressCapsuleClick }
}
