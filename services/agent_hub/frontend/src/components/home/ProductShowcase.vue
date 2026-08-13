<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from '@/i18n'

const { t } = useI18n()
const loaded = ref(false)
const stageElement = ref<HTMLElement | null>(null)
const showcaseWidth = 1280
const showcaseHeight = 800
const scale = ref(1)
let resizeObserver: ResizeObserver | undefined

const bundledShowcaseUrl = (() => {
  const moduleName = new URL(import.meta.url).pathname.split('/').pop() || 'showcase'
  const url = new URL('/app-showcase/showcase.html', window.location.origin)
  url.searchParams.set('revision', moduleName)
  return `${url.pathname}${url.search}`
})()

const source = computed(() => (
  String(import.meta.env.VITE_APP_SHOWCASE_URL || '').trim()
  || (import.meta.env.DEV ? 'http://127.0.0.1:5173/showcase.html' : bundledShowcaseUrl)
))

const screenStyle = computed(() => ({
  height: `${Math.round(showcaseHeight * scale.value)}px`,
  maxWidth: `${showcaseWidth}px`,
}))

const frameStyle = computed(() => ({
  width: `${showcaseWidth}px`,
  height: `${showcaseHeight}px`,
  transform: `scale(${scale.value})`,
}))

function updateScale(width: number) {
  scale.value = Math.min(1, width / showcaseWidth)
}

onMounted(() => {
  resizeObserver = new ResizeObserver(([entry]) => {
    if (entry) updateScale(entry.contentRect.width)
  })
  if (stageElement.value) {
    updateScale(stageElement.value.clientWidth)
    resizeObserver.observe(stageElement.value)
  }
})

onBeforeUnmount(() => resizeObserver?.disconnect())
</script>

<template>
  <section id="how-it-works" class="showcase" aria-labelledby="showcase-title">
    <div class="container">
      <header class="showcase__head">
        <span class="eyebrow">{{ t('home.showcaseEyebrow') }}</span>
        <h2 id="showcase-title">{{ t('home.showcaseTitle') }}</h2>
        <p>{{ t('home.showcaseSubtitle') }}</p>
      </header>

      <div ref="stageElement" class="showcase__stage">
        <div class="showcase__screen" :class="{ loaded }" :style="screenStyle">
          <div v-if="!loaded" class="showcase__loading" aria-hidden="true">
            <img src="/brand/combo/logo-mark.png" alt="" />
            <span>{{ t('home.demo.loading') }}</span>
          </div>
          <iframe
            :src="source"
            :style="frameStyle"
            :title="t('home.demo.frameTitle')"
            tabindex="-1"
            inert
            loading="eager"
            aria-hidden="true"
            @load="loaded = true"
          />
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.showcase { position: relative; overflow: clip; padding: clamp(88px, 11vw, 156px) 0; }
.showcase::before { position: absolute; inset: 34% 5% 0; z-index: -1; border-radius: 50%; background: radial-gradient(circle, color-mix(in srgb, var(--text-strong) 7%, transparent), transparent 64%); filter: blur(42px); content: ''; }
.showcase__head { width: min(820px, 100%); margin: 0 auto clamp(38px, 6vw, 70px); text-align: center; }
.showcase__head h2 { margin: 14px 0 20px; color: var(--text-strong); font-size: clamp(42px, 6vw, 76px); font-weight: 760; line-height: 1; letter-spacing: -.065em; }
.showcase__head p { max-width: 690px; margin: 0 auto; color: var(--text-secondary); font-size: 17px; line-height: 1.75; }
.showcase__stage { position: relative; left: 50%; width: min(1280px, calc(100vw - 34px)); transform: translateX(-50%); }
.showcase__screen { position: relative; width: 100%; margin: 0 auto; overflow: hidden; border: 1px solid var(--border-strong); border-radius: clamp(20px, 2.5vw, 32px); background: var(--surface); box-shadow: 0 42px 100px color-mix(in srgb, var(--text-strong) 14%, transparent); opacity: 0; transform: translateY(22px); transition: opacity 700ms var(--ease-out), transform 900ms var(--ease-out), height 160ms linear; }
.showcase__screen.loaded { opacity: 1; transform: none; }
.showcase__screen iframe { position: absolute; top: 0; left: 0; display: block; border: 0; background: #fff; pointer-events: none; transform-origin: top left; }
.showcase__loading { position: absolute; inset: 0; z-index: 1; display: grid; place-content: center; justify-items: center; gap: 12px; color: var(--text-secondary); background: var(--surface); font-size: 11px; }.showcase__loading img { width: 70px; height: 70px; object-fit: contain; filter: var(--brand-mark-filter); animation: loading-breathe 1.8s ease-in-out infinite; }
@keyframes loading-breathe { 50% { opacity: .45; transform: scale(.94); } }

@media (max-width: 720px) {
  .showcase { padding: 78px 0 96px; }.showcase__head { text-align: left; }.showcase__head h2 { font-size: 46px; }.showcase__head p { font-size: 15px; }.showcase__stage { width: calc(100vw - 24px); }.showcase__screen { border-radius: 14px; }
}
@media (prefers-reduced-motion: reduce) { .showcase__screen { transition: none; }.showcase__loading img { animation: none; } }
</style>
