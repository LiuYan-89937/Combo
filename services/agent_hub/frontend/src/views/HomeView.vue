<script setup lang="ts">
/*
 * Marketing home: hero, capability pipeline, architecture boundary, featured
 * agents (real API) and a download section driven by public config. Every
 * claim maps to a real product capability; download buttons disable when the
 * config has no URL rather than faking a link.
 */
import { computed, onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import BaseButton from '@/components/base/BaseButton.vue'
import BaseIcon, { type IconName } from '@/components/base/BaseIcon.vue'
import PackageCard from '@/components/hub/PackageCard.vue'
import StateBlock from '@/components/base/StateBlock.vue'
import SkeletonBlock from '@/components/base/SkeletonBlock.vue'
import { useI18n } from '@/i18n'
import { useConfigStore } from '@/stores/config'
import { useSeo, ORIGIN } from '@/composables/useSeo'
import { listPackages } from '@/api/packages'
import type { AgentRelease } from '@/api/types'

const { t } = useI18n()
const { config } = storeToRefs(useConfigStore())

const pipelineKeys: Array<{ key: string; icon: IconName }> = [
  { key: 'model', icon: 'cpu' },
  { key: 'make', icon: 'send' },
  { key: 'assemble', icon: 'boxes' },
  { key: 'run', icon: 'play' },
  { key: 'collaborate', icon: 'users' },
  { key: 'distribute', icon: 'upload' },
]

const factoryNodes = ['MODEL', 'TOOLS', 'MCP', 'SKILLS']

const featured = ref<AgentRelease[]>([])
const featuredState = ref<'loading' | 'ready' | 'empty' | 'error'>('loading')

async function loadFeatured() {
  featuredState.value = 'loading'
  try {
    const res = await listPackages({ limit: 6 })
    featured.value = res.items
    featuredState.value = res.items.length ? 'ready' : 'empty'
  } catch {
    featuredState.value = 'error'
  }
}

const hasDownload = computed(() => config.value.downloads.some((d) => d.url))

useSeo(() => ({
  title: t('home.title'),
  description: t('home.subtitle'),
  path: '/',
  jsonLd: {
    '@context': 'https://schema.org',
    '@type': 'SoftwareApplication',
    name: 'FastAgentFactory',
    applicationCategory: 'DeveloperApplication',
    operatingSystem: 'macOS, Windows',
    url: ORIGIN,
    offers: { '@type': 'Offer', price: '0', priceCurrency: 'USD' },
    description: t('home.subtitle'),
  },
}))

onMounted(loadFeatured)
</script>

<template>
  <div class="home">
    <!-- HERO -->
    <section class="hero">
      <div class="container hero__inner">
        <div class="hero__copy">
          <span class="hero__badge eyebrow">
            <span class="hero__badge-signal" aria-hidden="true" />
            {{ t('home.badge') }}
          </span>
          <h1 class="hero__title">{{ t('home.title') }}</h1>
          <p class="hero__subtitle">{{ t('home.subtitle') }}</p>
          <div class="hero__actions">
            <BaseButton to="/#download" size="lg" icon="download">{{ t('home.ctaDownload') }}</BaseButton>
            <BaseButton to="/hub" size="lg" variant="secondary" icon-end="arrow-right">
              {{ t('home.ctaHub') }}
            </BaseButton>
            <BaseButton
              :href="config.githubRepoUrl"
              external
              size="lg"
              variant="ghost"
              icon="github"
            >
              {{ t('home.ctaGithub') }}
            </BaseButton>
          </div>
        </div>

        <div class="factory-visual" aria-hidden="true">
          <div class="factory-visual__plane">
            <span class="factory-orbit factory-orbit--outer" />
            <span class="factory-orbit factory-orbit--inner" />
            <span class="factory-sweep" />
            <span
              v-for="(node, index) in factoryNodes"
              :key="node"
              class="factory-node-orbit"
              :class="`factory-node-orbit--${index}`"
            >
              <span class="factory-node">
                <i />
                {{ node }}
              </span>
            </span>
            <div class="factory-core">
              <span class="factory-core__halo" />
              <img src="/brand-mark.png" alt="" width="82" height="82" />
              <span class="factory-core__label">AGENT</span>
            </div>
          </div>
          <div class="factory-caption">
            <span><i /> RUNTIME READY</span>
            <span class="mono">04 / 04</span>
          </div>
        </div>
      </div>
    </section>

    <!-- PIPELINE -->
    <section class="section">
      <div class="container">
        <header class="block-head">
          <span class="eyebrow">FastAgentFactory</span>
          <h2 class="block-head__title">{{ t('home.pipelineTitle') }}</h2>
          <p class="block-head__sub">{{ t('home.pipelineSubtitle') }}</p>
        </header>
        <ol class="pipeline">
          <li
            v-for="(step, i) in pipelineKeys"
            :key="step.key"
            class="pipeline__step"
            :class="`pipeline__step--${i}`"
          >
            <span class="pipeline__scan" aria-hidden="true" />
            <span class="pipeline__num mono">{{ String(i + 1).padStart(2, '0') }}</span>
            <span class="pipeline__icon"><BaseIcon :name="step.icon" :size="22" /></span>
            <h3 class="pipeline__name">{{ t(`home.steps.${step.key}.name`) }}</h3>
            <p class="pipeline__desc">{{ t(`home.steps.${step.key}.desc`) }}</p>
          </li>
        </ol>
      </div>
    </section>

    <!-- ARCHITECTURE BOUNDARY -->
    <section class="section arch">
      <div class="container">
        <header class="block-head">
          <span class="eyebrow">Architecture</span>
          <h2 class="block-head__title">{{ t('home.archTitle') }}</h2>
          <p class="block-head__sub">{{ t('home.archSubtitle') }}</p>
        </header>
        <div class="arch__diagram" aria-hidden="true">
          <div class="arch__node arch__node--core">
            <BaseIcon name="cpu" :size="20" />
            <span>Desktop app</span>
            <small>Local runtime · workspaces</small>
          </div>
          <div class="arch__link">
            <span class="arch__dashes" />
            <span class="arch__link-label">metadata · auth · packages</span>
          </div>
          <div class="arch__node">
            <BaseIcon name="boxes" :size="20" />
            <span>AgentHub</span>
            <small>Distribution only</small>
          </div>
        </div>
      </div>
    </section>

    <!-- FEATURED -->
    <section class="section">
      <div class="container">
        <header class="block-head block-head--row">
          <div>
            <span class="eyebrow">AgentHub</span>
            <h2 class="block-head__title">{{ t('home.featuredTitle') }}</h2>
            <p class="block-head__sub">{{ t('home.featuredSubtitle') }}</p>
          </div>
          <BaseButton to="/hub" variant="secondary" icon-end="arrow-right" class="block-head__cta">
            {{ t('home.featuredViewAll') }}
          </BaseButton>
        </header>

        <div v-if="featuredState === 'loading'" class="grid">
          <div v-for="n in 3" :key="n" class="skeleton-card">
            <SkeletonBlock width="52px" height="52px" radius="var(--radius-md)" />
            <SkeletonBlock height="18px" width="60%" />
            <SkeletonBlock height="14px" />
            <SkeletonBlock height="14px" width="80%" />
          </div>
          <span class="visually-hidden" role="status">{{ t('common.loading') }}</span>
        </div>

        <div v-else-if="featuredState === 'ready'" class="grid">
          <PackageCard v-for="item in featured" :key="item.release_id" :release="item" />
        </div>

        <StateBlock
          v-else-if="featuredState === 'error'"
          kind="error"
          :title="t('common.error')"
          :body="t('common.serverError')"
          retryable
          @retry="loadFeatured"
        />

        <StateBlock
          v-else
          kind="empty"
          icon="boxes"
          :title="t('home.featuredEmptyTitle')"
          :body="t('home.featuredEmptyBody')"
        >
        </StateBlock>
        <div v-if="featuredState === 'empty'" class="home__empty-cta">
          <BaseButton to="/guide" variant="secondary" icon-end="arrow-right">
            {{ t('home.featuredEmptyCta') }}
          </BaseButton>
        </div>
      </div>
    </section>

    <!-- DOWNLOAD -->
    <section id="download" class="section download">
      <div class="container download__inner">
        <header class="block-head block-head--center">
          <span class="eyebrow">{{ t('nav.download') }}</span>
          <h2 class="block-head__title">{{ t('home.downloadTitle') }}</h2>
          <p class="block-head__sub">{{ t('home.downloadSubtitle') }}</p>
        </header>
        <div class="download__grid">
          <div v-for="d in config.downloads" :key="d.platform" class="download__card">
            <div class="download__meta">
              <h3 class="download__platform">{{ d.label }}</h3>
              <p class="download__arch">{{ d.arch }}</p>
              <p v-if="d.version" class="download__version mono">v{{ d.version }} · {{ d.sizeLabel }}</p>
            </div>
            <BaseButton
              v-if="d.url"
              :href="d.url"
              size="md"
              icon="download"
              block
            >
              {{ d.label }}
            </BaseButton>
            <BaseButton v-else variant="secondary" size="md" block disabled>
              {{ t('home.downloadUnavailable') }}
            </BaseButton>
          </div>
        </div>
        <p v-if="!hasDownload" class="download__soon">{{ t('home.downloadComingSoon') }}</p>
      </div>
    </section>
  </div>
</template>

<style scoped>
.home {
  position: relative;
  isolation: isolate;
  overflow: clip;
  background: var(--surface);
}
.home::before,
.home::after {
  content: '';
  position: fixed;
  z-index: -2;
  pointer-events: none;
}
.home::before {
  inset: -24vh -18vw;
  background:
    radial-gradient(circle at 14% 18%, color-mix(in srgb, var(--text-strong) 5%, transparent), transparent 28%),
    radial-gradient(circle at 82% 28%, color-mix(in srgb, var(--text-strong) 4%, transparent), transparent 31%),
    radial-gradient(circle at 52% 82%, color-mix(in srgb, var(--text-strong) 3%, transparent), transparent 34%);
  filter: blur(34px);
  animation: page-atmosphere 24s ease-in-out infinite alternate;
}
.home::after {
  z-index: -1;
  inset: -60px;
  background-image: radial-gradient(circle at 1px 1px, var(--border-strong) 0.8px, transparent 0);
  background-size: 44px 44px;
  opacity: 0.24;
  mask-image: linear-gradient(to bottom, #000, transparent 88%);
  animation: page-grid-drift 36s linear infinite;
}

/* HERO */
.hero {
  position: relative;
  overflow: hidden;
  min-height: min(760px, calc(100vh - var(--header-height)));
  display: flex;
  align-items: center;
  padding-block: clamp(76px, 10vw, 132px);
}
.hero__inner {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(360px, 0.85fr);
  align-items: center;
  gap: clamp(44px, 7vw, 108px);
}
.hero__copy {
  max-width: 800px;
}
.hero__badge {
  display: inline-flex;
  align-items: center;
  gap: 9px;
  padding: 6px 14px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-pill);
  color: var(--text-secondary);
  background: color-mix(in srgb, var(--surface) 70%, transparent);
  backdrop-filter: blur(8px);
}
.hero__badge-signal {
  position: relative;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--text-strong);
}
.hero__badge-signal::after {
  content: '';
  position: absolute;
  inset: -4px;
  border: 1px solid var(--text-strong);
  border-radius: 50%;
  animation: signal-breathe 2.8s var(--ease-out) infinite;
}
.hero__title {
  margin-top: var(--space-6);
  font-size: clamp(42px, 6vw, 78px);
  line-height: 0.99;
  letter-spacing: -0.05em;
  font-weight: 720;
  color: var(--text-strong);
}
.hero__subtitle {
  margin-top: var(--space-6);
  max-width: 660px;
  font-size: clamp(17px, 2.2vw, 21px);
  line-height: 1.6;
  color: var(--text-secondary);
}
.hero__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
  margin-top: var(--space-8);
}
/* Animated agent assembly core */
.factory-visual {
  position: relative;
  width: min(100%, 470px);
  justify-self: end;
}
.factory-visual__plane {
  position: relative;
  aspect-ratio: 1;
  border: 1px solid var(--border);
  border-radius: 42px;
  background:
    linear-gradient(var(--border) 1px, transparent 1px),
    linear-gradient(90deg, var(--border) 1px, transparent 1px),
    color-mix(in srgb, var(--surface) 82%, transparent);
  background-size: 42px 42px;
  box-shadow: inset 0 0 70px color-mix(in srgb, var(--text-strong) 3%, transparent);
  overflow: hidden;
  transform: perspective(900px) rotateY(-5deg) rotateX(2deg);
}
.factory-visual__plane::after {
  content: '';
  position: absolute;
  inset: 0;
  background: radial-gradient(circle at center, transparent 18%, color-mix(in srgb, var(--surface) 62%, transparent) 72%);
  pointer-events: none;
}
.factory-orbit {
  position: absolute;
  z-index: 1;
  left: 50%;
  top: 50%;
  border: 1px solid var(--border-strong);
  border-radius: 50%;
  transform: translate(-50%, -50%);
}
.factory-orbit--outer {
  width: 72%;
  height: 72%;
  border-style: dashed;
  animation: orbit-turn 32s linear infinite;
}
.factory-orbit--inner {
  width: 47%;
  height: 47%;
  opacity: 0.7;
  animation: orbit-turn-reverse 22s linear infinite;
}
.factory-sweep {
  position: absolute;
  z-index: 1;
  left: 50%;
  top: 50%;
  width: 36%;
  height: 1px;
  transform-origin: left center;
  background: linear-gradient(90deg, var(--text-strong), transparent);
  opacity: 0.22;
  animation: radar-sweep 9s linear infinite;
}
.factory-core {
  position: absolute;
  z-index: 3;
  left: 50%;
  top: 50%;
  display: grid;
  place-items: center;
  width: 126px;
  height: 126px;
  transform: translate(-50%, -50%);
  border: 1px solid var(--border-strong);
  border-radius: 34px;
  background: color-mix(in srgb, var(--surface) 24%, transparent);
  backdrop-filter: blur(5px);
}
.factory-core img {
  position: relative;
  z-index: 2;
  width: 82px;
  height: 82px;
  object-fit: contain;
  filter: var(--brand-mark-filter);
}
.factory-core__halo {
  position: absolute;
  inset: -15px;
  border: 1px solid var(--border-strong);
  border-radius: 42px;
  animation: core-pulse 3.6s var(--ease-out) infinite;
}
.factory-core__label {
  position: absolute;
  left: 50%;
  bottom: -29px;
  transform: translateX(-50%);
  font-family: var(--font-mono);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.28em;
  color: var(--text-secondary);
}
.factory-node-orbit {
  position: absolute;
  z-index: 4;
  inset: 14%;
  border-radius: 50%;
  animation: node-orbit 20s linear infinite;
}
.factory-node {
  position: absolute;
  left: 50%;
  top: -15px;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 7px 10px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-pill);
  background: color-mix(in srgb, var(--surface) 88%, transparent);
  backdrop-filter: blur(8px);
  font-family: var(--font-mono);
  font-size: 8px;
  font-weight: 650;
  letter-spacing: 0.13em;
  color: var(--text-secondary);
  transform: translateX(-50%);
  animation:
    node-counter-orbit 20s linear infinite,
    node-live 10s var(--ease-out) infinite;
}
.factory-node i,
.factory-caption i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}
.factory-node-orbit--0,
.factory-node-orbit--0 .factory-node {
  animation-delay: 0s, 0s;
}
.factory-node-orbit--1,
.factory-node-orbit--1 .factory-node {
  animation-delay: -5s, -5s;
}
.factory-node-orbit--2,
.factory-node-orbit--2 .factory-node {
  animation-delay: -10s, -10s;
}
.factory-node-orbit--3,
.factory-node-orbit--3 .factory-node {
  animation-delay: -15s, -15s;
}
.factory-caption {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 13px 4px 0;
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.12em;
}
.factory-caption span:first-child {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.factory-caption i {
  color: var(--success);
  box-shadow: 0 0 0 4px var(--success-surface);
}

/* SHARED BLOCK HEADS */
.block-head {
  max-width: 640px;
  margin-bottom: var(--space-12);
}
.block-head--center {
  margin-inline: auto;
  text-align: center;
}
.block-head--row {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--space-6);
  max-width: none;
}
.block-head__title {
  margin-top: var(--space-2);
  font-size: clamp(26px, 3.6vw, 38px);
  letter-spacing: -0.025em;
  font-weight: 640;
  color: var(--text-strong);
}
.block-head__sub {
  margin-top: var(--space-3);
  color: var(--text-secondary);
  font-size: 16px;
}
.block-head__cta {
  flex-shrink: 0;
}

/* PIPELINE */
.pipeline {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-4);
  list-style: none;
}
.pipeline__step {
  position: relative;
  overflow: hidden;
  padding: var(--space-6);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  animation: pipeline-focus 12s linear infinite;
  transition: border-color var(--dur-base) var(--ease-out), transform var(--dur-base) var(--ease-out);
}
.pipeline__step:hover {
  border-color: var(--border-strong);
  transform: translateY(-3px);
}
.pipeline__scan {
  position: absolute;
  inset: 0 auto auto 0;
  width: 100%;
  height: 2px;
  background: linear-gradient(90deg, transparent, var(--text-strong), transparent);
  transform: scaleX(0);
  animation: pipeline-scan 12s linear infinite;
}
.pipeline__step--1,
.pipeline__step--1 .pipeline__scan {
  animation-delay: 2s;
}
.pipeline__step--2,
.pipeline__step--2 .pipeline__scan {
  animation-delay: 4s;
}
.pipeline__step--3,
.pipeline__step--3 .pipeline__scan {
  animation-delay: 6s;
}
.pipeline__step--4,
.pipeline__step--4 .pipeline__scan {
  animation-delay: 8s;
}
.pipeline__step--5,
.pipeline__step--5 .pipeline__scan {
  animation-delay: 10s;
}
.pipeline__num {
  position: absolute;
  top: var(--space-6);
  right: var(--space-6);
  font-size: 13px;
  color: var(--text-muted);
}
.pipeline__icon {
  display: inline-grid;
  place-items: center;
  width: 44px;
  height: 44px;
  border-radius: var(--radius-md);
  background: var(--surface-subtle);
  border: 1px solid var(--border);
  color: var(--text-strong);
}
.pipeline__name {
  margin-top: var(--space-4);
  font-size: 18px;
  font-weight: 620;
  color: var(--text-strong);
}
.pipeline__desc {
  margin-top: var(--space-2);
  color: var(--text-secondary);
  font-size: 14px;
  line-height: 1.6;
}

/* ARCHITECTURE */
.arch {
  background: transparent;
}
.arch__diagram {
  display: flex;
  align-items: stretch;
  gap: var(--space-4);
  flex-wrap: wrap;
}
.arch__node {
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex: 1 1 240px;
  padding: var(--space-6);
  background: var(--surface);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-lg);
  color: var(--text-strong);
  font-weight: 600;
}
.arch__node small {
  font-weight: 450;
  color: var(--text-secondary);
  font-size: 13px;
}
.arch__node--core {
  border-color: var(--text-strong);
  border-width: 1.5px;
}
.arch__link {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding-inline: var(--space-2);
}
.arch__dashes {
  width: 64px;
  height: 0;
  border-top: 2px dashed var(--border-strong);
}
.arch__link-label {
  font-size: 12px;
  color: var(--text-muted);
  text-align: center;
}

/* GRID / CARDS */
.grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-4);
}
.skeleton-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-6);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
}
.home__empty-cta {
  display: flex;
  justify-content: center;
  margin-top: calc(-1 * var(--space-8));
}

/* DOWNLOAD */
.download {
  position: relative;
}
.download__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 340px));
  gap: var(--space-4);
  justify-content: center;
}
.download__card {
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
  padding: var(--space-8);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  text-align: center;
}
.download__platform {
  font-size: 20px;
  font-weight: 640;
  color: var(--text-strong);
}
.download__arch {
  color: var(--text-secondary);
  font-size: 14px;
  margin-top: 4px;
}
.download__version {
  margin-top: var(--space-2);
  font-size: 12px;
  color: var(--text-muted);
}
.download__soon {
  margin-top: var(--space-6);
  text-align: center;
  color: var(--text-muted);
  font-size: 14px;
}

@keyframes page-grid-drift {
  to { transform: translate3d(44px, 44px, 0); }
}
@keyframes page-atmosphere {
  from { transform: translate3d(-2%, -1%, 0) scale(0.96) rotate(-2deg); }
  to { transform: translate3d(3%, 4%, 0) scale(1.08) rotate(2deg); }
}
@keyframes signal-breathe {
  0%, 100% { opacity: 0; transform: scale(0.55); }
  32% { opacity: 0.42; }
  70% { opacity: 0; transform: scale(1.45); }
}
@keyframes orbit-turn {
  from { transform: translate(-50%, -50%) rotate(0deg); }
  to { transform: translate(-50%, -50%) rotate(360deg); }
}
@keyframes orbit-turn-reverse {
  from { transform: translate(-50%, -50%) rotate(360deg); }
  to { transform: translate(-50%, -50%) rotate(0deg); }
}
@keyframes radar-sweep {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
@keyframes node-orbit {
  to { transform: rotate(360deg); }
}
@keyframes node-counter-orbit {
  to { transform: translateX(-50%) rotate(-360deg); }
}
@keyframes core-pulse {
  0%, 100% { opacity: 0.28; transform: scale(0.94); }
  50% { opacity: 0.8; transform: scale(1.04); }
}
@keyframes node-live {
  0%, 16%, 100% {
    color: var(--text-secondary);
    border-color: var(--border-strong);
  }
  5%, 10% {
    color: var(--text-strong);
    border-color: var(--text-strong);
  }
}
@keyframes pipeline-focus {
  0%, 16%, 100% {
    border-color: var(--border);
    box-shadow: none;
  }
  4%, 11% {
    border-color: var(--border-strong);
    box-shadow: 0 10px 32px color-mix(in srgb, var(--text-strong) 7%, transparent);
  }
}
@keyframes pipeline-scan {
  0%, 16%, 100% { opacity: 0; transform: scaleX(0); }
  4%, 11% { opacity: 0.72; transform: scaleX(1); }
}

@media (max-width: 1023px) {
  .hero {
    min-height: auto;
  }
  .hero__inner {
    grid-template-columns: minmax(0, 1fr) minmax(300px, 0.72fr);
    gap: var(--space-8);
  }
  .pipeline,
  .grid {
    grid-template-columns: repeat(2, 1fr);
  }
}
@media (max-width: 820px) {
  .hero__inner {
    grid-template-columns: 1fr;
  }
  .factory-visual {
    width: min(88vw, 460px);
    justify-self: center;
  }
}
@media (max-width: 640px) {
  .hero {
    padding-block: var(--space-18);
  }
  .hero__title {
    font-size: clamp(40px, 14vw, 60px);
  }
  .factory-visual__plane {
    border-radius: 28px;
    transform: none;
  }
  .factory-core {
    width: 106px;
    height: 106px;
    border-radius: 28px;
  }
  .factory-core img {
    width: 70px;
    height: 70px;
    border-radius: 20px;
  }
  .pipeline,
  .grid,
  .download__grid {
    grid-template-columns: 1fr;
  }
  .block-head--row {
    flex-direction: column;
    align-items: flex-start;
  }
  .arch__link {
    flex-direction: row;
    width: 100%;
  }
  .arch__dashes {
    width: 100%;
  }
}
@media (prefers-reduced-motion: reduce) {
  .home::before,
  .home::after,
  .hero__badge-signal::after,
  .factory-orbit,
  .factory-sweep,
  .factory-core__halo,
  .factory-node-orbit,
  .factory-node,
  .pipeline__step,
  .pipeline__scan {
    animation: none;
  }
}
</style>
