<template>
  <span
    ref="rootElement"
    class="combo-frame-animation"
    :style="{
      '--frame-size': `${size}px`,
      '--frame-ratio': `${definition.width} / ${definition.height}`,
    }"
    aria-hidden="true"
  >
    <img :src="frameSource" alt="" draggable="false" />
  </span>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  comboFrameSource,
  getComboAnimation,
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
}>(), {
  size: 144,
  paused: false,
  fps: 0,
  phaseOffset: 0,
  loop: true,
})

const emit = defineEmits<{ complete: [] }>()
const definition = computed(() => getComboAnimation(props.character, props.action))
const frameIndex = ref(0)
const rootElement = ref<HTMLElement | null>(null)
const reducedMotion = ref(false)
const inViewport = ref(true)
const pageVisible = ref(true)
let timer: number | undefined
let observer: IntersectionObserver | undefined

const frameSource = computed(() => comboFrameSource(props.character, props.action, frameIndex.value))

function stop() {
  if (timer !== undefined) window.clearInterval(timer)
  timer = undefined
}

function start() {
  stop()
  frameIndex.value = props.phaseOffset % definition.value.frameCount
  if (props.paused || reducedMotion.value || !inViewport.value || !pageVisible.value) return
  const fps = props.fps > 0 ? props.fps : definition.value.defaultFps
  timer = window.setInterval(() => {
    const next = frameIndex.value + 1
    if (!props.loop && next >= definition.value.frameCount) {
      stop()
      emit('complete')
      return
    }
    frameIndex.value = next % definition.value.frameCount
  }, Math.round(1000 / fps))
}

watch(() => [props.character, props.action, props.paused, props.fps, props.phaseOffset, props.loop], start)

onMounted(() => {
  reducedMotion.value = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  pageVisible.value = document.visibilityState === 'visible'
  observer = new IntersectionObserver(([entry]) => {
    inViewport.value = entry?.isIntersecting ?? true
    start()
  })
  if (rootElement.value) observer.observe(rootElement.value)
  document.addEventListener('visibilitychange', handleVisibility)
  start()
})

onBeforeUnmount(() => {
  stop()
  observer?.disconnect()
  document.removeEventListener('visibilitychange', handleVisibility)
})

function handleVisibility() {
  pageVisible.value = document.visibilityState === 'visible'
  start()
}
</script>

<style scoped>
.combo-frame-animation {
  display: inline-grid;
  width: var(--frame-size);
  aspect-ratio: var(--frame-ratio);
  flex: none;
  place-items: center;
}
.combo-frame-animation img { display: block; width: 100%; height: 100%; object-fit: contain; user-select: none; }
:root[data-theme='dark'] .combo-frame-animation img { filter: invert(1); }
</style>
