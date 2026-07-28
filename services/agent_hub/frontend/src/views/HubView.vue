<script setup lang="ts">
/*
 * AgentHub explore page. Debounced search maps to the API `q` param; results
 * page with limit/offset via a "load more" control. Search races are cancelled
 * with an AbortController so a slow earlier query never overwrites a newer one.
 * No categories/tags/sorting — the API exposes none.
 */
import { onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import BaseButton from '@/components/base/BaseButton.vue'
import BaseIcon from '@/components/base/BaseIcon.vue'
import PackageCard from '@/components/hub/PackageCard.vue'
import StateBlock from '@/components/base/StateBlock.vue'
import SkeletonBlock from '@/components/base/SkeletonBlock.vue'
import { useI18n } from '@/i18n'
import { useSeo } from '@/composables/useSeo'
import { listPackages } from '@/api/packages'
import { ApiError, NetworkError } from '@/api/client'
import type { AgentRelease } from '@/api/types'

const PAGE_SIZE = 12
const { t } = useI18n()
const route = useRoute()
const router = useRouter()

const query = ref(typeof route.query.q === 'string' ? route.query.q : '')
const items = ref<AgentRelease[]>([])
const total = ref(0)
const offset = ref(0)
const state = ref<'loading' | 'ready' | 'empty' | 'error'>('loading')
const loadingMore = ref(false)
const errorRequestId = ref<string | undefined>()

let controller: AbortController | null = null
let debounce: ReturnType<typeof setTimeout> | undefined

async function fetchPage(reset: boolean) {
  controller?.abort()
  controller = new AbortController()
  if (reset) {
    state.value = 'loading'
    offset.value = 0
  } else {
    loadingMore.value = true
  }
  try {
    const res = await listPackages({
      q: query.value.trim() || undefined,
      limit: PAGE_SIZE,
      offset: offset.value,
      signal: controller.signal,
    })
    total.value = res.total
    items.value = reset ? res.items : [...items.value, ...res.items]
    state.value = items.value.length ? 'ready' : 'empty'
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') return
    errorRequestId.value = error instanceof ApiError ? error.requestId : undefined
    state.value = 'error'
    void (error instanceof NetworkError)
  } finally {
    loadingMore.value = false
  }
}

function loadMore() {
  offset.value += PAGE_SIZE
  void fetchPage(false)
}

function clearSearch() {
  query.value = ''
}

// Debounce input, sync to URL, and reset paging.
watch(query, (value) => {
  clearTimeout(debounce)
  debounce = setTimeout(() => {
    const q = value.trim()
    void router.replace({ query: q ? { q } : {} })
    void fetchPage(true)
  }, 280)
})

useSeo(() => ({
  title: t('hub.title'),
  description: t('hub.subtitle'),
  path: '/hub',
}))

onMounted(() => fetchPage(true))
</script>

<template>
  <div class="hub">
    <section class="hub__head">
      <div class="container">
        <h1 class="hub__title">{{ t('hub.title') }}</h1>
        <p class="hub__subtitle">{{ t('hub.subtitle') }}</p>
        <div class="search">
          <BaseIcon name="search" :size="19" class="search__icon" />
          <input
            v-model="query"
            type="search"
            class="search__input"
            :placeholder="t('hub.searchPlaceholder')"
            :aria-label="t('hub.searchLabel')"
            autocomplete="off"
          />
          <button
            v-if="query"
            type="button"
            class="search__clear"
            :aria-label="t('hub.clearSearch')"
            @click="clearSearch"
          >
            <BaseIcon name="close" :size="16" />
          </button>
        </div>
      </div>
    </section>

    <section class="container hub__body">
      <p v-if="state === 'ready'" class="hub__count" aria-live="polite">
        {{ query.trim() ? t('hub.resultCountQuery', { total, q: query.trim() }) : t('hub.resultCount', { total }) }}
      </p>

      <div v-if="state === 'loading'" class="grid">
        <div v-for="n in 6" :key="n" class="skeleton-card">
          <SkeletonBlock width="52px" height="52px" radius="var(--radius-md)" />
          <SkeletonBlock height="18px" width="55%" />
          <SkeletonBlock height="14px" />
          <SkeletonBlock height="14px" width="80%" />
        </div>
        <span class="visually-hidden" role="status">{{ t('common.loading') }}</span>
      </div>

      <template v-else-if="state === 'ready'">
        <div class="grid">
          <PackageCard v-for="item in items" :key="item.release_id" :release="item" />
        </div>
        <div v-if="items.length < total" class="hub__more">
          <BaseButton
            variant="secondary"
            :loading="loadingMore"
            icon-end="chevron-down"
            @click="loadMore"
          >
            {{ t('hub.loadMore') }}
          </BaseButton>
        </div>
      </template>

      <StateBlock
        v-else-if="state === 'error'"
        kind="error"
        :title="t('common.error')"
        :body="t('common.serverError')"
        :request-id="errorRequestId"
        retryable
        @retry="fetchPage(true)"
      />

      <StateBlock
        v-else
        kind="empty"
        icon="search"
        :title="query.trim() ? t('hub.emptyTitle') : t('hub.emptyTitle')"
        :body="query.trim() ? t('hub.emptyBody') : t('hub.emptyNoData')"
      />
      <div v-if="state === 'empty' && query.trim()" class="hub__more">
        <BaseButton variant="secondary" size="sm" @click="clearSearch">{{ t('hub.clearSearch') }}</BaseButton>
      </div>
    </section>
  </div>
</template>

<style scoped>
.hub__head {
  padding-block: var(--space-18) var(--space-8);
  border-bottom: 1px solid var(--border);
  background: var(--surface-subtle);
}
.hub__title {
  font-size: clamp(30px, 5vw, 46px);
  letter-spacing: -0.03em;
  font-weight: 680;
  color: var(--text-strong);
}
.hub__subtitle {
  margin-top: var(--space-3);
  color: var(--text-secondary);
  font-size: 17px;
  max-width: 560px;
}
.search {
  position: relative;
  display: flex;
  align-items: center;
  margin-top: var(--space-8);
  max-width: 620px;
}
.search__icon {
  position: absolute;
  left: var(--space-4);
  color: var(--text-muted);
  pointer-events: none;
}
.search__input {
  width: 100%;
  height: 54px;
  padding-inline: 48px;
  background: var(--surface);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-pill);
  font-family: inherit;
  font-size: 16px;
  color: var(--text);
  transition: border-color var(--dur-fast) var(--ease-out), box-shadow var(--dur-fast) var(--ease-out);
}
.search__input:focus {
  outline: none;
  border-color: var(--text-strong);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--text-strong) 12%, transparent);
}
.search__input::-webkit-search-cancel-button {
  display: none;
}
.search__clear {
  position: absolute;
  right: var(--space-3);
  display: inline-grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border: none;
  border-radius: 50%;
  background: var(--surface-subtle);
  color: var(--text-secondary);
  cursor: pointer;
}
.search__clear:hover {
  color: var(--text-strong);
  background: var(--surface-pressed);
}

.hub__body {
  padding-block: var(--space-8) var(--space-24);
}
.hub__count {
  margin-bottom: var(--space-6);
  color: var(--text-secondary);
  font-size: 14px;
}
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
.hub__more {
  display: flex;
  justify-content: center;
  margin-top: var(--space-8);
}
@media (max-width: 1023px) {
  .grid {
    grid-template-columns: repeat(2, 1fr);
  }
}
@media (max-width: 640px) {
  .grid {
    grid-template-columns: 1fr;
  }
}
</style>
