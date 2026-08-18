<template>
  <span
    ref="rootElement"
    class="combo-frame-animation"
    :style="{
      '--combo-frame-width': `${size}px`,
      '--combo-frame-ratio': `${animation.width} / ${animation.height}`,
      '--combo-frame-source': `url(${frameSource})`,
      '--combo-frame-tint': tint,
    }"
    :class="{ 'is-tinted': Boolean(tint) }"
    aria-hidden="true"
  >
    <template v-if="tint">
      <img class="tint-base" :src="frameSource" alt="" draggable="false" />
      <span class="tinted-frame" />
    </template>
    <img v-else :src="frameSource" alt="" draggable="false" />
  </span>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  getComboAnimation,
  getComboMascotFrameSource,
  type ComboAnimationAction,
  type ComboCharacter,
} from './comboMascotAssets'
import { preloadComboMascotFrame } from './comboMascotFrameLoader'

const props = withDefaults(defineProps<{
  character: ComboCharacter
  action: ComboAnimationAction
  size?: number
  paused?: boolean
  fps?: number
  phaseOffset?: number
  loop?: boolean
  tint?: string
}>(), {
  size: 144,
  paused: false,
  fps: 0,
  phaseOffset: 0,
  loop: true,
  tint: '',
})

const emit = defineEmits<{ complete: [] }>()

const animation = computed(() => getComboAnimation(props.character, props.action))
const initialFrameIndex = ((props.phaseOffset % animation.value.frameCount) + animation.value.frameCount)
  % animation.value.frameCount
const rootElement = ref<HTMLElement | null>(null)
const frameIndex = ref(initialFrameIndex)
const displayedFrameSource = ref(getComboMascotFrameSource(
  props.character,
  props.action,
  initialFrameIndex,
))
const framesReady = ref(false)
const reducedMotion = ref(false)
const inViewport = ref(true)
const pageVisible = ref(true)
let mounted = false
let preparationVersion = 0
let playbackCompleted = false
let animationTimer: number | undefined
let visibilityObserver: IntersectionObserver | undefined
let reducedMotionQuery: MediaQueryList | undefined

const frameSources = computed(() => Array.from(
  { length: animation.value.frameCount },
  (_, index) => getComboMascotFrameSource(props.character, props.action, index),
))
const frameSource = computed(() => displayedFrameSource.value)

function stopAnimation() {
  if (animationTimer !== undefined) {
    window.clearInterval(animationTimer)
    animationTimer = undefined
  }
}

function normalizedInitialFrame(): number {
  const frameCount = animation.value.frameCount
  return ((props.phaseOffset % frameCount) + frameCount) % frameCount
}

function canPlay(): boolean {
  return framesReady.value
    && !playbackCompleted
    && !props.paused
    && !reducedMotion.value
    && inViewport.value
    && pageVisible.value
}

function synchronizePlayback(restartTimer = false) {
  if (!canPlay()) {
    stopAnimation()
    return
  }
  if (animationTimer !== undefined && !restartTimer) return

  stopAnimation()

  const fps = props.fps > 0 ? props.fps : animation.value.defaultFps
  animationTimer = window.setInterval(() => {
    const nextFrame = frameIndex.value + 1
    if (!props.loop && nextFrame >= animation.value.frameCount) {
      stopAnimation()
      playbackCompleted = true
      emit('complete')
      return
    }
    frameIndex.value = nextFrame % animation.value.frameCount
    displayedFrameSource.value = frameSources.value[frameIndex.value]
  }, Math.round(1000 / fps))
}

async function prepareAnimation() {
  const version = ++preparationVersion
  stopAnimation()
  framesReady.value = false
  playbackCompleted = false

  const sources = frameSources.value
  const initialFrame = normalizedInitialFrame()
  const preloadTasks = sources.map(preloadComboMascotFrame)
  const initialFrameReady = await preloadTasks[initialFrame]
  if (version !== preparationVersion) return

  frameIndex.value = initialFrame
  if (initialFrameReady) displayedFrameSource.value = sources[initialFrame]

  const loadedFrames = await Promise.all(preloadTasks)
  if (version !== preparationVersion) return
  framesReady.value = loadedFrames.every(Boolean)
  synchronizePlayback()
}

watch(
  () => [props.character, props.action, props.phaseOffset] as const,
  () => {
    if (mounted) void prepareAnimation()
  },
)

watch(
  () => [props.paused, props.fps, props.loop] as const,
  ([, , loop], previous) => {
    if (!mounted) return
    if (loop && previous && !previous[2]) playbackCompleted = false
    synchronizePlayback(Boolean(previous && props.fps !== previous[1]))
  },
)

onMounted(() => {
  mounted = true
  reducedMotionQuery = window.matchMedia('(prefers-reduced-motion: reduce)')
  reducedMotion.value = reducedMotionQuery.matches
  pageVisible.value = document.visibilityState === 'visible'
  visibilityObserver = new IntersectionObserver(([entry]) => {
    inViewport.value = entry?.isIntersecting ?? true
    synchronizePlayback()
  })
  if (rootElement.value) visibilityObserver.observe(rootElement.value)
  document.addEventListener('visibilitychange', handlePageVisibility)
  reducedMotionQuery.addEventListener('change', handleReducedMotionChange)
  void prepareAnimation()
})

onBeforeUnmount(() => {
  mounted = false
  preparationVersion += 1
  stopAnimation()
  visibilityObserver?.disconnect()
  document.removeEventListener('visibilitychange', handlePageVisibility)
  reducedMotionQuery?.removeEventListener('change', handleReducedMotionChange)
})

function handlePageVisibility() {
  pageVisible.value = document.visibilityState === 'visible'
  synchronizePlayback()
}

function handleReducedMotionChange(event: MediaQueryListEvent) {
  reducedMotion.value = event.matches
  synchronizePlayback()
}
</script>

<style scoped>
.combo-frame-animation {
  display: inline-grid;
  width: var(--combo-frame-width);
  aspect-ratio: var(--combo-frame-ratio);
  flex: none;
  place-items: center;
}

.combo-frame-animation img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: contain;
  user-select: none;
}

.tinted-frame {
  grid-area: 1 / 1;
  display: block;
  width: 100%;
  height: 100%;
  background: var(--combo-frame-tint);
  mix-blend-mode: screen;
  mask: var(--combo-frame-source) center / contain no-repeat;
  -webkit-mask: var(--combo-frame-source) center / contain no-repeat;
}

.tint-base {
  grid-area: 1 / 1;
}

:root[data-theme='dark'] .combo-frame-animation img {
  filter: invert(1);
}

:root[data-theme='dark'] .combo-frame-animation.is-tinted img {
  filter: none;
}
</style>
