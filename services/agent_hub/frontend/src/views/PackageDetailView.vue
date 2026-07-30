<script setup lang="ts">
/*
 * Package detail: identity, download, capability overview from the validation
 * report, dependency lists, static-check notes, changelog and version history.
 * Every value comes from the real detail payload; nothing is invented. The
 * download button navigates the browser to the backend 307 redirect endpoint.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import AgentAvatar from '@/components/base/AgentAvatar.vue'
import BaseBadge from '@/components/base/BaseBadge.vue'
import BaseButton from '@/components/base/BaseButton.vue'
import BaseIcon from '@/components/base/BaseIcon.vue'
import CopyButton from '@/components/base/CopyButton.vue'
import StateBlock from '@/components/base/StateBlock.vue'
import SkeletonBlock from '@/components/base/SkeletonBlock.vue'
import { useI18n } from '@/i18n'
import { useSeo, ORIGIN } from '@/composables/useSeo'
import { fetchPackageDetail, releaseDownloadUrl } from '@/api/packages'
import { formatBytes, formatCount, formatDate, shortHash } from '@/composables/useFormat'
import { ApiError } from '@/api/client'
import type { AgentPackageDetail, AgentRelease } from '@/api/types'

const props = defineProps<{ publisher: string; packageId: string }>()
const { t, locale } = useI18n()

const detail = ref<AgentPackageDetail | null>(null)
const state = ref<'loading' | 'ready' | 'error' | 'notfound'>('loading')
const errorRequestId = ref<string | undefined>()
const selectedId = ref<string | null>(null)

const active = computed<AgentRelease | null>(() => {
  if (!detail.value) return null
  return detail.value.versions.find((v) => v.release_id === selectedId.value) ?? detail.value.latest
})
const validation = computed(() => active.value?.validation ?? null)
const warnings = computed(() => validation.value?.warnings ?? [])

async function load() {
  state.value = 'loading'
  try {
    const res = await fetchPackageDetail(props.publisher, props.packageId)
    detail.value = res
    selectedId.value = res.latest.release_id
    state.value = 'ready'
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      state.value = 'notfound'
      return
    }
    errorRequestId.value = error instanceof ApiError ? error.requestId : undefined
    state.value = 'error'
  }
}

watch(() => [props.publisher, props.packageId], load)

useSeo(() => {
  const d = detail.value
  if (!d) return { title: t('hub.title'), path: `/hub/${props.publisher}/${props.packageId}` }
  return {
    title: `${d.name || d.package_id} · ${d.publisher}`,
    description: d.description || t('hub.subtitle'),
    path: `/hub/${encodeURIComponent(d.publisher)}/${encodeURIComponent(d.package_id)}`,
    jsonLd: {
      '@context': 'https://schema.org',
      '@type': 'SoftwareSourceCode',
      name: d.name || d.package_id,
      description: d.description,
      codeRepository: `${ORIGIN}/hub/${d.publisher}/${d.package_id}`,
      author: { '@type': 'Person', name: d.publisher },
      softwareVersion: d.latest.version,
    },
  }
})

onMounted(load)
</script>

<template>
  <div class="detail">
    <div v-if="state === 'loading'" class="container detail__loading">
      <SkeletonBlock width="72px" height="72px" radius="var(--radius-lg)" />
      <SkeletonBlock height="30px" width="40%" />
      <SkeletonBlock height="16px" width="70%" />
      <SkeletonBlock height="16px" width="55%" />
      <span class="visually-hidden" role="status">{{ t('common.loading') }}</span>
    </div>

    <StateBlock
      v-else-if="state === 'notfound'"
      kind="empty"
      icon="x-circle"
      :title="t('notFound.title')"
      :body="t('common.notFound')"
    />
    <StateBlock
      v-else-if="state === 'error'"
      kind="error"
      :title="t('common.error')"
      :body="t('common.serverError')"
      :request-id="errorRequestId"
      retryable
      @retry="load"
    />

    <template v-else-if="state === 'ready' && detail && active">
      <!-- HEADER -->
      <header class="detail__head">
        <div class="container detail__head-inner">
          <nav class="crumbs" aria-label="breadcrumb">
            <RouterLink to="/hub" class="crumbs__link">{{ t('nav.hub') }}</RouterLink>
            <BaseIcon name="chevron-right" :size="14" />
            <span class="crumbs__current">{{ detail.name || detail.package_id }}</span>
          </nav>

          <div class="detail__identity">
            <AgentAvatar :publisher="detail.publisher" :package-id="detail.package_id" :size="76" />
            <div class="detail__id-text">
              <h1 class="detail__name">{{ detail.name || detail.package_id }}</h1>
              <p class="detail__publisher">
                {{ detail.publisher }} <span class="detail__sep">/</span>
                <span class="mono">{{ detail.package_id }}</span>
              </p>
            </div>
          </div>

          <p class="detail__desc">{{ detail.description || '—' }}</p>

          <div class="detail__facts">
            <BaseBadge tone="success"><BaseIcon name="shield-check" :size="13" /> {{ t('detail.validationPassed') }}</BaseBadge>
            <span class="detail__fact mono">v{{ active.version }}</span>
            <span class="detail__fact">
              <BaseIcon name="download" :size="14" />
              {{ t('hub.downloadCount', { count: formatCount(active.download_count) }) }}
            </span>
            <span class="detail__fact">{{ formatBytes(active.size_bytes) }}</span>
            <span class="detail__fact">{{ t('common.published') }} {{ formatDate(active.published_at, locale) }}</span>
          </div>

          <div class="detail__actions">
            <BaseButton :href="releaseDownloadUrl(active.release_id)" size="lg" icon="download">
              {{ t('detail.downloadPackage') }}
            </BaseButton>
          </div>
        </div>
      </header>

      <div class="container detail__grid">
        <div class="detail__main">
          <!-- CAPABILITIES -->
          <section v-if="validation" class="panel">
            <h2 class="panel__title">{{ t('detail.capabilities') }}</h2>
            <div class="caps">
              <div class="caps__group">
                <span class="caps__label"><BaseIcon name="wrench" :size="15" /> {{ t('detail.packageTools') }}</span>
                <div v-if="validation.tools.package_tools.length" class="chips">
                  <span v-for="tool in validation.tools.package_tools" :key="tool" class="chip mono">{{ tool }}</span>
                </div>
                <span v-else class="caps__none">{{ t('detail.none') }}</span>
              </div>
              <div class="caps__group">
                <span class="caps__label"><BaseIcon name="boxes" :size="15" /> {{ t('detail.builtinTools') }}</span>
                <div v-if="validation.tools.builtin_tools.length" class="chips">
                  <span v-for="tool in validation.tools.builtin_tools" :key="tool" class="chip mono">{{ tool }}</span>
                </div>
                <span v-else class="caps__none">{{ t('detail.none') }}</span>
              </div>
              <div class="caps__group">
                <span class="caps__label"><BaseIcon name="cpu" :size="15" /> {{ t('detail.mcpServers') }}</span>
                <div v-if="validation.tools.mcp_servers.length" class="chips">
                  <span v-for="mcp in validation.tools.mcp_servers" :key="mcp" class="chip mono">{{ mcp }}</span>
                </div>
                <span v-else class="caps__none">{{ t('detail.none') }}</span>
              </div>
            </div>
          </section>

          <!-- DEPENDENCIES -->
          <section v-if="validation" class="panel">
            <h2 class="panel__title">{{ t('detail.dependencyOverview') }}</h2>
            <div class="deps">
              <div class="deps__col">
                <span class="deps__head">{{ t('detail.pythonDeps') }} <em>{{ validation.dependencies.python_count }}</em></span>
                <ul v-if="validation.dependencies.python.length" class="deps__list">
                  <li v-for="dep in validation.dependencies.python" :key="dep" class="mono">{{ dep }}</li>
                </ul>
                <span v-else class="caps__none">{{ t('detail.none') }}</span>
              </div>
              <div class="deps__col">
                <span class="deps__head">{{ t('detail.npmDeps') }} <em>{{ validation.dependencies.npm_count }}</em></span>
                <ul v-if="validation.dependencies.npm.length" class="deps__list">
                  <li v-for="dep in validation.dependencies.npm" :key="dep" class="mono">{{ dep }}</li>
                </ul>
                <span v-else class="caps__none">{{ t('detail.none') }}</span>
              </div>
              <div class="deps__col">
                <span class="deps__head">{{ t('detail.systemDeps') }} <em>{{ validation.dependencies.system_count }}</em></span>
                <ul v-if="validation.dependencies.system.length" class="deps__list">
                  <li v-for="dep in validation.dependencies.system" :key="dep" class="mono">{{ dep }}</li>
                </ul>
                <span v-else class="caps__none">{{ t('detail.none') }}</span>
              </div>
            </div>
          </section>

          <!-- STATIC CHECKS -->
          <section class="panel">
            <h2 class="panel__title">{{ t('detail.validationTitle') }}</h2>
            <p class="panel__note">{{ t('detail.validationNote') }}</p>
            <ul v-if="warnings.length" class="warnings">
              <li v-for="(w, i) in warnings" :key="i" class="warnings__item">
                <BaseIcon name="alert" :size="16" class="warnings__icon" />
                <div>
                  <p class="warnings__msg">{{ w.message }}</p>
                  <p v-if="w.path" class="warnings__path mono">{{ w.path }}</p>
                </div>
              </li>
            </ul>
            <p v-else class="caps__none">{{ t('detail.noWarnings') }}</p>
          </section>

          <!-- CHANGELOG -->
          <section class="panel">
            <h2 class="panel__title">{{ t('detail.changelog') }}</h2>
            <p v-if="active.changelog" class="changelog">{{ active.changelog }}</p>
            <p v-else class="caps__none">{{ t('detail.noChangelog') }}</p>
          </section>
        </div>

        <!-- SIDEBAR -->
        <aside class="detail__side">
          <section class="side-card">
            <h3 class="side-card__title">{{ t('detail.sha256') }}</h3>
            <p class="side-card__hash mono">{{ shortHash(active.sha256) }}</p>
            <CopyButton :value="active.sha256" :label="t('detail.sha256')" />
          </section>

          <section v-if="validation" class="side-card">
            <h3 class="side-card__title">{{ t('detail.fileCount') }}</h3>
            <dl class="side-stats">
              <div><dt>{{ t('detail.fileCount') }}</dt><dd class="mono">{{ validation.file_count }}</dd></div>
              <div><dt>{{ t('common.size') }}</dt><dd class="mono">{{ formatBytes(validation.archive_size) }}</dd></div>
            </dl>
          </section>

          <section class="side-card">
            <h3 class="side-card__title">{{ t('detail.versionHistory') }}</h3>
            <ul class="versions">
              <li v-for="v in detail.versions" :key="v.release_id">
                <button
                  type="button"
                  class="versions__btn"
                  :class="{ 'versions__btn--active': v.release_id === active.release_id }"
                  @click="selectedId = v.release_id"
                >
                  <span class="mono">v{{ v.version }}</span>
                  <span class="versions__date">{{ formatDate(v.published_at, locale) }}</span>
                </button>
              </li>
            </ul>
          </section>
        </aside>
      </div>
    </template>
  </div>
</template>

<style scoped>
.detail__loading {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  padding-block: var(--space-18);
}

/* HEADER */
.detail__head {
  padding-block: var(--space-12) var(--space-8);
  border-bottom: 1px solid var(--border);
  background: var(--surface-subtle);
}
.detail__head-inner {
  max-width: 900px;
}
.crumbs {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--text-muted);
  font-size: 14px;
  margin-bottom: var(--space-6);
}
.crumbs__link {
  color: var(--text-secondary);
  text-decoration: none;
}
.crumbs__link:hover {
  color: var(--text-strong);
}
.crumbs__current {
  color: var(--text);
}
.detail__identity {
  display: flex;
  align-items: center;
  gap: var(--space-4);
}
.detail__name {
  font-size: clamp(28px, 4.5vw, 40px);
  letter-spacing: -0.03em;
  font-weight: 680;
  color: var(--text-strong);
  line-height: 1.1;
}
.detail__publisher {
  margin-top: 4px;
  color: var(--text-secondary);
  font-size: 15px;
}
.detail__sep {
  color: var(--text-muted);
  padding-inline: 2px;
}
.detail__desc {
  margin-top: var(--space-6);
  max-width: 700px;
  font-size: 17px;
  line-height: 1.6;
  color: var(--text-secondary);
}
.detail__facts {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
  margin-top: var(--space-6);
  font-size: 14px;
  color: var(--text-secondary);
}
.detail__fact {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
.detail__actions {
  margin-top: var(--space-8);
}

/* GRID */
.detail__grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 320px;
  gap: var(--space-12);
  padding-block: var(--space-12) var(--space-24);
}
.detail__main {
  display: flex;
  flex-direction: column;
  gap: var(--space-8);
  min-width: 0;
}

/* PANELS */
.panel {
  padding: var(--space-8);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
}
.panel__title {
  font-size: 19px;
  font-weight: 640;
  color: var(--text-strong);
  margin-bottom: var(--space-6);
}
.panel__note {
  margin-top: calc(-1 * var(--space-3));
  margin-bottom: var(--space-6);
  color: var(--text-muted);
  font-size: 13px;
}

/* CAPABILITIES */
.caps {
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
}
.caps__group {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.caps__label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
}
.caps__none {
  color: var(--text-muted);
  font-size: 14px;
}
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.chip {
  padding: 4px 10px;
  background: var(--surface-subtle);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  font-size: 13px;
  color: var(--text);
}

/* DEPENDENCIES */
.deps {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-6);
}
.deps__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
  padding-bottom: var(--space-2);
  border-bottom: 1px solid var(--border);
  margin-bottom: var(--space-3);
}
.deps__head em {
  font-style: normal;
  color: var(--text-muted);
  font-weight: 500;
}
.deps__list {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 13px;
  color: var(--text-secondary);
}
.deps__list li {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* WARNINGS */
.warnings {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.warnings__item {
  display: flex;
  gap: var(--space-3);
  padding: var(--space-4);
  background: var(--warning-surface);
  border-radius: var(--radius-md);
}
.warnings__icon {
  color: var(--warning);
  flex-shrink: 0;
  margin-top: 2px;
}
.warnings__msg {
  font-size: 14px;
  color: var(--text);
}
.warnings__path {
  margin-top: 2px;
  font-size: 12px;
  color: var(--text-muted);
}

/* CHANGELOG */
.changelog {
  white-space: pre-wrap;
  line-height: 1.7;
  color: var(--text-secondary);
  font-size: 15px;
}

/* SIDEBAR */
.detail__side {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  position: sticky;
  top: calc(var(--header-height) + var(--space-4));
  align-self: start;
}
.side-card {
  padding: var(--space-6);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
}
.side-card__title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: var(--space-3);
}
.side-card__hash {
  font-size: 14px;
  color: var(--text);
  margin-bottom: var(--space-3);
  word-break: break-all;
}
.side-stats {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.side-stats > div {
  display: flex;
  justify-content: space-between;
  font-size: 14px;
}
.side-stats dt {
  color: var(--text-secondary);
}
.side-stats dd {
  color: var(--text-strong);
  font-weight: 550;
}
.versions {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 2px;
  max-height: 320px;
  overflow-y: auto;
}
.versions__btn {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding: var(--space-3);
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text);
  font-family: inherit;
  font-size: 14px;
  cursor: pointer;
  text-align: left;
  transition: background var(--dur-fast) var(--ease-out);
}
.versions__btn:hover {
  background: var(--surface-subtle);
}
.versions__btn--active {
  background: var(--surface-pressed);
  font-weight: 600;
}
.versions__date {
  color: var(--text-muted);
  font-size: 12px;
}

@media (max-width: 1023px) {
  .detail__grid {
    grid-template-columns: 1fr;
    gap: var(--space-8);
  }
  .detail__side {
    position: static;
  }
  .deps {
    grid-template-columns: 1fr;
  }
}
@media (max-width: 640px) {
  .detail__identity {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>

