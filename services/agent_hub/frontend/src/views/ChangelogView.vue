<script setup lang="ts">
import { onMounted, ref } from 'vue'
import BaseButton from '@/components/base/BaseButton.vue'
import BaseIcon from '@/components/base/BaseIcon.vue'
import MarkdownContent from '@/components/base/MarkdownContent.vue'
import StateBlock from '@/components/base/StateBlock.vue'
import { listAppReleases } from '@/api/appReleases'
import type { AppRelease } from '@/api/types'
import { formatBytes, formatDate } from '@/composables/useFormat'
import { useI18n } from '@/i18n'
import { useSeo } from '@/composables/useSeo'

const { t, locale } = useI18n()
const releases = ref<AppRelease[]>([])
const state = ref<'loading' | 'ready' | 'empty' | 'error'>('loading')

async function load() {
  state.value = 'loading'
  try {
    releases.value = await listAppReleases(50)
    state.value = releases.value.length ? 'ready' : 'empty'
  } catch {
    state.value = 'error'
  }
}

function platformLabel(platform: string): string {
  if (platform === 'macos') return 'macOS'
  if (platform === 'windows') return 'Windows'
  if (platform === 'linux') return 'Linux'
  return platform
}

useSeo(() => ({
  title: t('changelog.title'),
  description: t('changelog.subtitle'),
  path: '/changelog',
}))

onMounted(load)
</script>

<template>
  <div class="changelog">
    <section class="changelog__hero">
      <div class="container">
        <span class="eyebrow">Combo</span>
        <h1>{{ t('changelog.title') }}</h1>
        <p>{{ t('changelog.subtitle') }}</p>
      </div>
    </section>

    <section class="container changelog__body">
      <StateBlock
        v-if="state === 'loading'"
        kind="loading"
        :title="t('common.loading')"
      />
      <StateBlock
        v-else-if="state === 'error'"
        kind="error"
        :title="t('common.error')"
        :body="t('common.serverError')"
        retryable
        @retry="load"
      />
      <StateBlock
        v-else-if="state === 'empty'"
        kind="empty"
        icon="clock"
        :title="t('changelog.emptyTitle')"
        :body="t('changelog.emptyBody')"
      />

      <ol v-else class="release-list">
        <li v-for="(release, index) in releases" :key="release.app_release_id" class="release">
          <div class="release__rail" aria-hidden="true">
            <span class="release__dot" />
            <span v-if="index < releases.length - 1" class="release__line" />
          </div>
          <article class="release__card">
            <header class="release__head">
              <div>
                <div class="release__version-row">
                  <span class="release__version mono">{{ release.tag_name }}</span>
                  <span v-if="index === 0" class="release__latest">{{ t('common.latest') }}</span>
                </div>
                <h2>{{ release.title }}</h2>
                <time :datetime="release.published_at">
                  {{ formatDate(release.published_at, locale) }}
                </time>
              </div>
              <BaseButton
                v-if="release.github_url"
                :href="release.github_url"
                external
                variant="secondary"
                size="sm"
                icon-end="arrow-up-right"
              >
                GitHub
              </BaseButton>
            </header>

            <MarkdownContent :source="release.notes_markdown" class="release__notes" />

            <div v-if="release.assets.length" class="release__assets">
              <a
                v-for="asset in release.assets"
                :key="asset.asset_id"
                :href="asset.download_url"
                class="asset"
              >
                <span class="asset__icon"><BaseIcon name="download" :size="17" /></span>
                <span>
                  <strong>{{ platformLabel(asset.platform) }}</strong>
                  <small>{{ asset.architecture }} · {{ formatBytes(asset.size_bytes) }}</small>
                </span>
              </a>
            </div>
          </article>
        </li>
      </ol>
    </section>
  </div>
</template>

<style scoped>
.changelog__hero {
  padding-block: var(--space-18) var(--space-12);
  border-bottom: 1px solid var(--border);
}
.changelog__hero h1 {
  margin: var(--space-3) 0 var(--space-2);
  color: var(--text-strong);
  font-size: clamp(2.25rem, 5vw, 4.4rem);
  line-height: 1;
  letter-spacing: -0.06em;
}
.changelog__hero p {
  max-width: 660px;
  color: var(--text-secondary);
  font-size: 1.08rem;
}
.changelog__body {
  max-width: 980px;
  padding-block: var(--space-12) var(--space-24);
}
.release-list {
  margin: 0;
  padding: 0;
  list-style: none;
}
.release {
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr);
}
.release__rail {
  position: relative;
  display: flex;
  justify-content: center;
}
.release__dot {
  position: relative;
  z-index: 1;
  width: 11px;
  height: 11px;
  margin-top: 30px;
  border: 3px solid var(--surface);
  border-radius: 50%;
  background: var(--text-strong);
  box-shadow: 0 0 0 1px var(--border-strong);
}
.release__line {
  position: absolute;
  top: 40px;
  bottom: -30px;
  width: 1px;
  background: var(--border-strong);
}
.release__card {
  margin-bottom: var(--space-8);
  padding: clamp(var(--space-6), 4vw, var(--space-8));
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: var(--surface);
}
.release__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
  padding-bottom: var(--space-6);
  border-bottom: 1px solid var(--border);
}
.release__version-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.release__version {
  color: var(--text-strong);
  font-weight: 650;
}
.release__latest {
  padding: 2px 8px;
  border-radius: var(--radius-pill);
  background: var(--text-strong);
  color: var(--surface);
  font-size: 11px;
  font-weight: 650;
}
.release__head h2 {
  margin: var(--space-2) 0 2px;
  color: var(--text-strong);
  font-size: 1.45rem;
  letter-spacing: -0.025em;
}
.release__head time {
  color: var(--text-secondary);
  font-size: 13px;
}
.release__notes {
  padding-block: var(--space-6);
}
.release__assets {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: var(--space-3);
  padding-top: var(--space-4);
  border-top: 1px solid var(--border);
}
.asset {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text);
  text-decoration: none;
  transition: border-color var(--dur-fast) var(--ease-out),
    transform var(--dur-fast) var(--ease-out);
}
.asset:hover {
  border-color: var(--border-strong);
  transform: translateY(-1px);
}
.asset__icon {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  border-radius: var(--radius-sm);
  background: var(--surface-subtle);
}
.asset strong,
.asset small {
  display: block;
}
.asset strong {
  color: var(--text-strong);
  font-size: 14px;
}
.asset small {
  margin-top: 1px;
  color: var(--text-secondary);
  font-size: 12px;
}
@media (max-width: 640px) {
  .release {
    grid-template-columns: 18px minmax(0, 1fr);
  }
  .release__head {
    flex-direction: column;
  }
}
</style>
