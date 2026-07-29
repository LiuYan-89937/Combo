<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import BaseButton from '@/components/base/BaseButton.vue'
import BaseIcon from '@/components/base/BaseIcon.vue'
import {
  approveAgentRelease,
  listPendingAgentReleases,
  listPublishedAgentReleases,
  rejectAgentRelease,
  unpublishAgentRelease,
} from '@/api/admin'
import { ApiError } from '@/api/client'
import type { AgentRelease } from '@/api/types'
import { formatBytes, formatDate } from '@/composables/useFormat'

const pending = ref<AgentRelease[]>([])
const published = ref<AgentRelease[]>([])
const loading = ref(true)
const loadError = ref('')
const busy = ref('')
const errors = reactive<Record<string, string>>({})
const reasons = reactive<Record<string, string>>({})

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    ;[pending.value, published.value] = await Promise.all([
      listPendingAgentReleases(),
      listPublishedAgentReleases(),
    ])
  } catch (error) {
    loadError.value = error instanceof ApiError ? error.message : '审核列表加载失败'
  } finally {
    loading.value = false
  }
}

async function approve(release: AgentRelease) {
  busy.value = release.release_id
  errors[release.release_id] = ''
  try {
    await approveAgentRelease(release.release_id)
    await load()
  } catch (error) {
    errors[release.release_id] =
      error instanceof ApiError ? error.message : '批准失败'
  } finally {
    busy.value = ''
  }
}

async function reject(release: AgentRelease) {
  const reason = (reasons[release.release_id] || '').trim()
  if (!reason) {
    errors[release.release_id] = '请填写驳回原因'
    return
  }
  busy.value = release.release_id
  errors[release.release_id] = ''
  try {
    await rejectAgentRelease(release.release_id, reason)
    await load()
  } catch (error) {
    errors[release.release_id] =
      error instanceof ApiError ? error.message : '驳回失败'
  } finally {
    busy.value = ''
  }
}

async function unpublish(release: AgentRelease) {
  busy.value = release.release_id
  errors[release.release_id] = ''
  try {
    await unpublishAgentRelease(release.release_id)
    await load()
  } catch (error) {
    errors[release.release_id] =
      error instanceof ApiError ? error.message : '下架失败'
  } finally {
    busy.value = ''
  }
}

onMounted(load)
</script>

<template>
  <div class="reviews">
    <div v-if="loadError" class="reviews__failure">
      <p>{{ loadError }}</p>
      <BaseButton variant="secondary" size="sm" @click="load">重新加载</BaseButton>
    </div>
    <section>
      <header class="reviews__head">
        <div>
          <span class="eyebrow">Pending review</span>
          <h2>待审核 Agent 包</h2>
        </div>
        <span>{{ pending.length }}</span>
      </header>
      <p v-if="loading" class="empty">正在加载…</p>
      <p v-else-if="!pending.length" class="empty">当前没有待审核版本</p>
      <article v-for="release in pending" :key="release.release_id" class="review-card">
        <header>
          <div>
            <span class="mono">{{ release.publisher }}/{{ release.package_id }}</span>
            <h3>{{ release.name }} · v{{ release.version }}</h3>
          </div>
          <span>{{ formatBytes(release.size_bytes) }}</span>
        </header>
        <p>{{ release.description }}</p>
        <div class="review-card__meta">
          <span>SHA-256 <code>{{ release.sha256.slice(0, 16) }}…</code></span>
          <span>{{ formatDate(release.created_at, 'zh-CN') }}</span>
        </div>
        <label>
          <span>驳回原因</span>
          <textarea v-model="reasons[release.release_id]" rows="2" placeholder="仅驳回时必填" />
        </label>
        <p v-if="errors[release.release_id]" class="review-card__error">
          {{ errors[release.release_id] }}
        </p>
        <footer>
          <BaseButton
            variant="secondary"
            :disabled="busy === release.release_id"
            @click="reject(release)"
          >
            驳回
          </BaseButton>
          <BaseButton
            :loading="busy === release.release_id"
            icon="check"
            @click="approve(release)"
          >
            批准发布
          </BaseButton>
        </footer>
      </article>
    </section>

    <section>
      <header class="reviews__head">
        <div>
          <span class="eyebrow">Published</span>
          <h2>已发布 Agent 包</h2>
        </div>
        <span>{{ published.length }}</span>
      </header>
      <p v-if="!loading && !published.length" class="empty">暂无已发布版本</p>
      <article v-for="release in published" :key="release.release_id" class="published-card">
        <span class="published-card__icon"><BaseIcon name="boxes" :size="18" /></span>
        <span>
          <strong>{{ release.name }} · v{{ release.version }}</strong>
          <small>{{ release.publisher }}/{{ release.package_id }}</small>
        </span>
        <BaseButton
          variant="ghost"
          size="sm"
          :loading="busy === release.release_id"
          @click="unpublish(release)"
        >
          下架
        </BaseButton>
      </article>
    </section>
  </div>
</template>

<style scoped>
.reviews {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(320px, 0.8fr);
  gap: var(--space-6);
}
.reviews__failure {
  grid-column: 1 / -1;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-4);
  border: 1px solid var(--danger);
  border-radius: var(--radius-md);
  color: var(--danger);
}
.reviews section {
  min-width: 0;
}
.reviews__head,
.review-card header,
.review-card footer,
.published-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
}
.reviews__head {
  margin-bottom: var(--space-4);
}
.reviews h2 {
  margin: 2px 0 0;
  color: var(--text-strong);
  line-height: 1.2;
}
.reviews__head > span {
  display: grid;
  place-items: center;
  min-width: 34px;
  height: 34px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  font-family: var(--font-mono);
  font-size: 12px;
}
.empty {
  padding: var(--space-8);
  border: 1px dashed var(--border-strong);
  border-radius: var(--radius-md);
  color: var(--text-secondary);
  text-align: center;
}
.review-card,
.published-card {
  margin-bottom: var(--space-3);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--surface);
}
.review-card {
  padding: var(--space-5, 20px);
}
.review-card h3 {
  margin: var(--space-1) 0 0;
  color: var(--text-strong);
}
.review-card header > span,
.review-card p,
.review-card__meta,
.published-card small {
  color: var(--text-secondary);
  font-size: 13px;
}
.review-card > p {
  margin-block: var(--space-3);
}
.review-card__meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-4);
  margin-bottom: var(--space-4);
}
.review-card code {
  font-family: var(--font-mono);
}
.review-card label {
  display: grid;
  gap: var(--space-2);
  margin-bottom: var(--space-4);
  color: var(--text-strong);
  font-size: 13px;
}
.review-card textarea {
  width: 100%;
  padding: var(--space-3);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  background: var(--surface);
  color: var(--text);
  font: inherit;
  resize: vertical;
}
.review-card__error {
  color: var(--danger) !important;
}
.review-card footer {
  justify-content: flex-end;
}
.published-card {
  padding: var(--space-3);
}
.published-card__icon {
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  border-radius: var(--radius-sm);
  background: var(--surface-subtle);
}
.published-card > span:nth-child(2) {
  min-width: 0;
  margin-right: auto;
}
.published-card strong,
.published-card small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
@media (max-width: 900px) {
  .reviews {
    grid-template-columns: 1fr;
  }
}
</style>
