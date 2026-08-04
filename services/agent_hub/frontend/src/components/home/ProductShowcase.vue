<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from '@/i18n'

const { t } = useI18n()
const loaded = ref(false)
const bundledShowcaseUrl = (() => {
  const moduleName = new URL(import.meta.url).pathname.split('/').pop() || 'showcase'
  const url = new URL('/app-showcase/showcase.html', window.location.origin)
  url.searchParams.set('revision', moduleName)
  return `${url.pathname}${url.search}`
})()
const source = computed(() => (
  String(import.meta.env.VITE_APP_SHOWCASE_URL || '').trim()
  || (import.meta.env.DEV
    ? 'http://127.0.0.1:5173/showcase.html'
    : bundledShowcaseUrl)
))
</script>

<template>
  <section class="product-showcase" aria-labelledby="product-showcase-title">
    <div class="container">
      <header class="product-showcase__head">
        <span class="eyebrow">Inside FastAgentFactory</span>
        <h2 id="product-showcase-title">{{ t('home.showcaseTitle') }}</h2>
      </header>

      <div class="product-showcase__stage">
        <div class="product-showcase__window" :class="{ 'is-loaded': loaded }">
          <div class="product-showcase__chrome" aria-hidden="true">
            <span />
            <span />
            <span />
            <strong>FastAgentFactory</strong>
          </div>
          <div class="product-showcase__viewport">
            <div v-if="!loaded" class="product-showcase__loading" aria-hidden="true">
              <span />
              <span />
              <span />
            </div>
            <iframe
              :src="source"
              title="FastAgentFactory 应用实时演示"
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
.product-showcase {
  position: relative;
  padding: clamp(72px, 10vw, 144px) 0;
  overflow: clip;
}

.product-showcase::before {
  content: '';
  position: absolute;
  inset: 18% 2% 3%;
  z-index: -1;
  border-radius: 50%;
  background: radial-gradient(circle at 50% 38%, color-mix(in srgb, var(--ink) 7%, transparent), transparent 58%);
  filter: blur(42px);
  opacity: .7;
}

.product-showcase__head {
  width: min(760px, 100%);
  margin: 0 auto clamp(34px, 5vw, 62px);
  text-align: center;
}

.product-showcase__head h2 {
  margin: 12px 0 16px;
  font-size: clamp(34px, 5.4vw, 68px);
  font-weight: 760;
  line-height: 1.03;
  letter-spacing: -.055em;
  color: var(--ink);
}

.product-showcase__head p {
  max-width: 650px;
  margin: 0 auto;
  color: var(--muted);
  font-size: clamp(16px, 1.8vw, 20px);
  line-height: 1.72;
}

.product-showcase__stage {
  position: relative;
  left: 50%;
  display: flex;
  justify-content: center;
  width: min(1380px, calc(100vw - 34px));
  margin-inline: 0;
  perspective: 1800px;
  transform: translateX(-50%);
}

.product-showcase__window {
  position: relative;
  width: 100%;
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--ink) 16%, transparent);
  border-radius: clamp(20px, 2.4vw, 34px);
  background: #fff;
  box-shadow:
    0 52px 110px rgba(0, 0, 0, .16),
    0 16px 42px rgba(0, 0, 0, .08),
    inset 0 1px rgba(255, 255, 255, .8);
  opacity: 0;
  transform: translateY(28px) rotateX(2deg) scale(.985);
  transition:
    opacity 900ms cubic-bezier(.16, 1, .3, 1),
    transform 1100ms cubic-bezier(.16, 1, .3, 1);
}

.product-showcase__window.is-loaded {
  opacity: 1;
  transform: translateY(0) rotateX(0) scale(1);
}

.product-showcase__chrome {
  position: relative;
  height: 42px;
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 0 16px;
  border-bottom: 1px solid rgba(0, 0, 0, .055);
  background: rgba(255, 255, 255, .94);
}

.product-showcase__chrome span {
  width: 10px;
  height: 10px;
  border: 1px solid rgba(0, 0, 0, .18);
  border-radius: 50%;
  background: #fff;
}

.product-showcase__chrome strong {
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
  color: rgba(0, 0, 0, .54);
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: .12em;
  text-transform: uppercase;
}

.product-showcase__viewport {
  position: relative;
  aspect-ratio: 16 / 9.2;
  overflow: hidden;
  background: #fff;
}

.product-showcase__viewport iframe {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  border: 0;
  background: #fff;
  pointer-events: none;
}

.product-showcase__loading {
  position: absolute;
  inset: 0;
  z-index: 1;
  display: grid;
  grid-template-columns: 20% 1fr 24%;
  gap: 1px;
  background: rgba(0, 0, 0, .05);
}

.product-showcase__loading span {
  background: linear-gradient(100deg, #fff 20%, #f7f7f7 45%, #fff 70%);
  background-size: 240% 100%;
  animation: showcase-loading 1.4s ease-in-out infinite;
}

@keyframes showcase-loading {
  from { background-position: 100% 0; }
  to { background-position: -120% 0; }
}

@media (max-width: 820px) {
  .product-showcase {
    padding: 72px 0 88px;
  }

  .product-showcase__stage {
    width: 1180px;
    transform-origin: left top;
    transform: translateX(-50%) scale(.62);
    margin-bottom: calc(-38% + 30px);
  }
}

@media (max-width: 560px) {
  .product-showcase__stage {
    transform: translateX(-50%) scale(.42);
    margin-bottom: calc(-55% + 20px);
  }
}

@media (prefers-reduced-motion: reduce) {
  .product-showcase__window {
    transition: none;
  }

  .product-showcase__loading span {
    animation: none;
  }
}
</style>
