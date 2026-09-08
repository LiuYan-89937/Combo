<template>
  <span
    ref="anchorRef"
    class="control-hint"
    @mouseenter="showHint"
    @mouseleave="hideHint"
    @focusin="showHint"
    @focusout="handleFocusOut"
  >
    <slot />

    <Teleport to="body">
      <span
        v-if="visible && !disabled"
        ref="hintRef"
        class="control-hint-content"
        :class="[`placement-${placement}`, { positioned }]"
        :style="hintStyle"
        role="tooltip"
      >
        {{ label }}
      </span>
    </Teleport>
  </span>
</template>

<script setup lang="ts">
import {
  computed,
  nextTick,
  onBeforeUnmount,
  ref,
  watch,
  type CSSProperties,
} from 'vue'

const props = withDefaults(defineProps<{
  label: string
  disabled?: boolean
  placement?: 'top' | 'bottom'
}>(), {
  disabled: false,
  placement: 'top',
})

const VIEWPORT_MARGIN = 8
const ANCHOR_GAP = 10
const ARROW_MARGIN = 10

const anchorRef = ref<HTMLElement | null>(null)
const hintRef = ref<HTMLElement | null>(null)
const visible = ref(false)
const positioned = ref(false)
const coordinates = ref({ top: 0, left: 0, arrowLeft: 0 })
let positionFrame: number | null = null

const hintStyle = computed<CSSProperties>(() => ({
  top: `${coordinates.value.top}px`,
  left: `${coordinates.value.left}px`,
  '--control-hint-arrow-left': `${coordinates.value.arrowLeft}px`,
}))

function showHint() {
  if (props.disabled || visible.value) return
  visible.value = true
  positioned.value = false
  window.addEventListener('resize', schedulePosition)
  window.addEventListener('scroll', schedulePosition, true)
  void nextTick(schedulePosition)
}

function hideHint() {
  visible.value = false
  positioned.value = false
  removePositionListeners()
}

function handleFocusOut(event: FocusEvent) {
  const nextTarget = event.relatedTarget
  if (nextTarget instanceof Node && anchorRef.value?.contains(nextTarget)) return
  hideHint()
}

function schedulePosition() {
  if (!visible.value || positionFrame !== null) return
  positionFrame = window.requestAnimationFrame(() => {
    positionFrame = null
    updatePosition()
  })
}

function updatePosition() {
  const anchor = anchorRef.value
  const hint = hintRef.value
  if (!anchor || !hint) return

  const anchorRect = anchor.getBoundingClientRect()
  const hintRect = hint.getBoundingClientRect()
  const anchorCenter = anchorRect.left + anchorRect.width / 2
  const maximumLeft = Math.max(
    VIEWPORT_MARGIN,
    window.innerWidth - hintRect.width - VIEWPORT_MARGIN,
  )
  const left = Math.min(
    maximumLeft,
    Math.max(VIEWPORT_MARGIN, anchorCenter - hintRect.width / 2),
  )
  const top = props.placement === 'top'
    ? anchorRect.top - hintRect.height - ANCHOR_GAP
    : anchorRect.bottom + ANCHOR_GAP
  const arrowLeft = Math.min(
    hintRect.width - ARROW_MARGIN,
    Math.max(ARROW_MARGIN, anchorCenter - left),
  )

  coordinates.value = { top, left, arrowLeft }
  positioned.value = true
}

function removePositionListeners() {
  window.removeEventListener('resize', schedulePosition)
  window.removeEventListener('scroll', schedulePosition, true)
  if (positionFrame !== null) {
    window.cancelAnimationFrame(positionFrame)
    positionFrame = null
  }
}

watch(
  () => [props.label, props.placement, props.disabled],
  () => {
    if (props.disabled) hideHint()
    else if (visible.value) void nextTick(schedulePosition)
  },
)

onBeforeUnmount(removePositionListeners)
</script>

<style scoped>
.control-hint {
  position: relative;
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
}

.control-hint-content {
  position: fixed;
  z-index: 12000;
  width: max-content;
  max-width: min(280px, calc(100vw - 16px));
  padding: 7px 10px;
  border-radius: 8px;
  background: var(--app-text);
  box-shadow: var(--app-shadow-md);
  color: var(--app-surface);
  font-size: 12px;
  font-weight: 550;
  line-height: 1.35;
  opacity: 0;
  pointer-events: none;
  transition: opacity .1s ease;
  white-space: normal;
}

.control-hint-content.positioned {
  opacity: 1;
}

.control-hint-content::after {
  position: absolute;
  left: var(--control-hint-arrow-left);
  width: 8px;
  height: 8px;
  background: var(--app-text);
  content: '';
}

.control-hint-content.placement-top::after {
  top: 100%;
  transform: translate(-50%, -4px) rotate(45deg);
}

.control-hint-content.placement-bottom::after {
  bottom: 100%;
  transform: translate(-50%, 4px) rotate(45deg);
}

@media (prefers-reduced-motion: reduce) {
  .control-hint-content {
    transition: none;
  }
}
</style>
