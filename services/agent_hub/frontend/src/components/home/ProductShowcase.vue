<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useI18n } from '@/i18n'
import { useThemeStore } from '@/stores/theme'

const { t, locale } = useI18n()
const { theme } = storeToRefs(useThemeStore())
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

const source = computed(() => {
  const configured = String(import.meta.env.VITE_APP_SHOWCASE_URL || '').trim()
  const base = configured
    || (import.meta.env.DEV ? 'http://127.0.0.1:5173/showcase.html' : bundledShowcaseUrl)
  const url = new URL(base, window.location.origin)
  url.searchParams.set('lang', locale.value)
  url.searchParams.set('theme', theme.value)
  return url.origin === window.location.origin
    ? `${url.pathname}${url.search}`
    : url.toString()
})

watch([locale, theme], () => {
  loaded.value = false
})

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
        <div>
          <span class="eyebrow">{{ t('home.showcaseEyebrow') }}</span>
          <h2 id="showcase-title">{{ t('home.showcaseTitle') }}</h2>
        </div>
        <p>{{ t('home.showcaseSubtitle') }}</p>
      </header>

      <div ref="stageElement" class="showcase__stage">
        <div class="showcase__bar" aria-hidden="true">
          <span><i />{{ t('home.demo.live') }}</span>
          <span>{{ t('home.demo.caption') }}</span>
        </div>
        <div class="showcase__viewport">
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
    </div>
  </section>
</template>

<style scoped>
.showcase { position: relative; overflow: clip; padding: clamp(96px, 10vw, 144px) 0; }
.showcase::before { position: absolute; inset: 28% 0 0; z-index: -1; background: linear-gradient(180deg, transparent, var(--surface-subtle) 32%, var(--surface-subtle)); content: ''; }
.showcase__head { display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(300px, .55fr); align-items: end; gap: clamp(36px, 8vw, 120px); margin-bottom: clamp(40px, 5vw, 64px); }
.showcase__head h2 { max-width: 800px; margin: 14px 0 0; color: var(--text-strong); font-size: clamp(48px, 6vw, 78px); font-weight: 760; line-height: .98; letter-spacing: -.065em; }
.showcase__head p { margin: 0 0 4px; color: var(--text-secondary); font-size: 16px; line-height: 1.75; }
.showcase__stage { position: relative; left: 50%; width: min(1320px, calc(100vw - 32px)); transform: translateX(-50%); }
.showcase__bar { display: flex; align-items: center; justify-content: space-between; padding: 0 4px 13px; color: var(--text-muted); font: 10px/1.2 var(--font-mono); letter-spacing: .06em; text-transform: uppercase; }
.showcase__bar span { display: inline-flex; align-items: center; gap: 8px; }
.showcase__bar i { width: 6px; height: 6px; border-radius: 50%; background: var(--text-strong); animation: live-pulse 1.8s ease-in-out infinite; }
.showcase__viewport { padding: clamp(5px, .7vw, 9px); border: 1px solid var(--border-strong); border-radius: clamp(18px, 2vw, 28px); background: var(--surface); box-shadow: 0 36px 90px color-mix(in srgb, var(--text-strong) 11%, transparent); }
.showcase__screen { position: relative; width: 100%; margin: 0 auto; overflow: hidden; border: 1px solid var(--border); border-radius: clamp(13px, 1.5vw, 20px); background: var(--surface); opacity: 0; transform: translateY(12px); transition: opacity 600ms var(--ease-out), transform 800ms var(--ease-out), height 160ms linear; }
.showcase__screen.loaded { opacity: 1; transform: none; }
.showcase__screen iframe { position: absolute; top: 0; left: 0; display: block; border: 0; background: var(--surface); pointer-events: none; transform-origin: top left; }
.showcase__loading { position: absolute; inset: 0; z-index: 1; display: grid; place-content: center; justify-items: center; gap: 12px; color: var(--text-secondary); background: var(--surface); font-size: 11px; }.showcase__loading img { width: 70px; height: 70px; object-fit: contain; filter: var(--brand-mark-filter); animation: loading-breathe 1.8s ease-in-out infinite; }
@keyframes loading-breathe { 50% { opacity: .45; transform: scale(.94); } }
@keyframes live-pulse { 50% { opacity: .3; transform: scale(.72); } }

@media (max-width: 720px) {
  .showcase { padding: 76px 0 92px; }.showcase__head { grid-template-columns: 1fr; gap: 20px; }.showcase__head h2 { font-size: 46px; }.showcase__head p { font-size: 15px; }.showcase__stage { width: calc(100vw - 20px); }.showcase__bar span:last-child { display: none; }.showcase__viewport { border-radius: 15px; }.showcase__screen { border-radius: 10px; }
}
@media (prefers-reduced-motion: reduce) { .showcase__screen { transition: none; }.showcase__loading img, .showcase__bar i { animation: none; } }
</style>
