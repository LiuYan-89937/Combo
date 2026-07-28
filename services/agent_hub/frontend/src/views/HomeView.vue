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
        <span class="hero__badge eyebrow">{{ t('home.badge') }}</span>
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
        <p class="hero__note">{{ t('home.notLocalPrivacy') }}</p>
      </div>
      <div class="hero__grid" aria-hidden="true" />
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
          <li v-for="(step, i) in pipelineKeys" :key="step.key" class="pipeline__step">
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
/* HERO */
.hero {
  position: relative;
  overflow: hidden;
  padding-block: clamp(72px, 12vw, 152px);
  border-bottom: 1px solid var(--border);
}
.hero__inner {
  position: relative;
  z-index: 1;
  max-width: 860px;
}
.hero__badge {
  display: inline-block;
  padding: 6px 14px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-pill);
  color: var(--text-secondary);
}
.hero__title {
  margin-top: var(--space-6);
  font-size: clamp(38px, 6.4vw, 76px);
  line-height: 1.02;
  letter-spacing: -0.035em;
  font-weight: 680;
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
.hero__note {
  margin-top: var(--space-6);
  font-size: 13px;
  color: var(--text-muted);
  max-width: 620px;
}
.hero__grid {
  position: absolute;
  inset: 0;
  background-image: radial-gradient(circle at 1px 1px, var(--border-strong) 1px, transparent 0);
  background-size: 40px 40px;
  mask-image: radial-gradient(ellipse 80% 70% at 78% 20%, #000 0%, transparent 72%);
  opacity: 0.5;
  pointer-events: none;
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
  padding: var(--space-6);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  transition: border-color var(--dur-base) var(--ease-out);
}
.pipeline__step:hover {
  border-color: var(--border-strong);
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
  background: var(--surface-subtle);
  border-block: 1px solid var(--border);
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
  border-top: 1px solid var(--border);
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

@media (max-width: 1023px) {
  .pipeline,
  .grid {
    grid-template-columns: repeat(2, 1fr);
  }
}
@media (max-width: 640px) {
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
</style>

