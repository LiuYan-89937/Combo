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
    <span v-if="tint" class="tinted-frame" />
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
const rootElement = ref<HTMLElement | null>(null)
const frameIndex = ref(0)
const reducedMotion = ref(false)
const inViewport = ref(true)
const pageVisible = ref(true)
let animationTimer: number | undefined
let visibilityObserver: IntersectionObserver | undefined

const frameSource = computed(() => getComboMascotFrameSource(
  props.character,
  props.action,
  frameIndex.value,
))

function stopAnimation() {
  if (animationTimer !== undefined) {
    window.clearInterval(animationTimer)
    animationTimer = undefined
  }
}

function startAnimation() {
  stopAnimation()
  frameIndex.value = props.phaseOffset % animation.value.frameCount
  if (props.paused || reducedMotion.value || !inViewport.value || !pageVisible.value) return

  const fps = props.fps > 0 ? props.fps : animation.value.defaultFps
  animationTimer = window.setInterval(() => {
    const nextFrame = frameIndex.value + 1
    if (!props.loop && nextFrame >= animation.value.frameCount) {
      stopAnimation()
      emit('complete')
      return
    }
    frameIndex.value = nextFrame % animation.value.frameCount
  }, Math.round(1000 / fps))
}

watch(
  () => [props.character, props.action, props.paused, props.fps, props.phaseOffset, props.loop] as const,
  startAnimation,
)

onMounted(() => {
  reducedMotion.value = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  pageVisible.value = document.visibilityState === 'visible'
  visibilityObserver = new IntersectionObserver(([entry]) => {
    inViewport.value = entry?.isIntersecting ?? true
    startAnimation()
  })
  if (rootElement.value) visibilityObserver.observe(rootElement.value)
  document.addEventListener('visibilitychange', handlePageVisibility)
  startAnimation()
})

onBeforeUnmount(() => {
  stopAnimation()
  visibilityObserver?.disconnect()
  document.removeEventListener('visibilitychange', handlePageVisibility)
})

function handlePageVisibility() {
  pageVisible.value = document.visibilityState === 'visible'
  startAnimation()
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
  display: block;
  width: 100%;
  height: 100%;
  background: var(--combo-frame-tint);
  mask: var(--combo-frame-source) center / contain no-repeat;
  -webkit-mask: var(--combo-frame-source) center / contain no-repeat;
}

:root[data-theme='dark'] .combo-frame-animation img {
  filter: invert(1);
}
</style>
