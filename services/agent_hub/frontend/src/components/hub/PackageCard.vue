<script setup lang="ts">
/*
 * Compact card for a published release in a grid. Shows only fields the API
 * actually returns — name, publisher, description, version, size, real
 * download count, and validation-derived capability counts. No ratings, tags
 * or categories (no backend contract for those).
 */
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import AgentAvatar from '@/components/base/AgentAvatar.vue'
import BaseBadge from '@/components/base/BaseBadge.vue'
import BaseIcon from '@/components/base/BaseIcon.vue'
import { formatBytes, formatCount } from '@/composables/useFormat'
import { useI18n } from '@/i18n'
import type { AgentRelease } from '@/api/types'

const props = defineProps<{ release: AgentRelease }>()
const { t } = useI18n()

const to = computed(
  () => `/hub/${encodeURIComponent(props.release.publisher)}/${encodeURIComponent(props.release.package_id)}`,
)

const pythonCount = computed(() => props.release.validation?.dependencies.python_count ?? 0)
const toolCount = computed(() => props.release.validation?.tools.package_tools.length ?? 0)
const mcpCount = computed(() => props.release.validation?.tools.mcp_servers.length ?? 0)
</script>

<template>
  <RouterLink :to="to" class="card">
    <div class="card__head">
      <AgentAvatar :publisher="release.publisher" :package-id="release.package_id" :size="52" />
      <div class="card__id">
        <h3 class="card__name clamp-1">{{ release.name || release.package_id }}</h3>
        <span class="card__publisher clamp-1">{{ release.publisher }}</span>
      </div>
    </div>

    <p class="card__desc clamp-2">{{ release.description || '—' }}</p>

    <div class="card__caps">
      <BaseBadge v-if="pythonCount" tone="neutral" size="sm">{{ t('hub.cardPython') }} · {{ pythonCount }}</BaseBadge>
      <BaseBadge v-if="toolCount" tone="neutral" size="sm">{{ t('hub.cardTools') }} · {{ toolCount }}</BaseBadge>
      <BaseBadge v-if="mcpCount" tone="neutral" size="sm">{{ t('hub.cardMcp') }} · {{ mcpCount }}</BaseBadge>
    </div>

    <div class="card__foot">
      <span class="card__version mono">v{{ release.version }}</span>
      <span class="card__meta">
        <BaseIcon name="download" :size="14" />
        {{ formatCount(release.download_count) }}
      </span>
      <span class="card__meta">{{ formatBytes(release.size_bytes) }}</span>
      <BaseIcon name="arrow-right" :size="16" class="card__go" />
    </div>
  </RouterLink>
</template>

<style scoped>
.card {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  height: 100%;
  padding: var(--space-6);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  text-decoration: none;
  color: inherit;
  transition: border-color var(--dur-base) var(--ease-out),
    transform var(--dur-base) var(--ease-out), box-shadow var(--dur-base) var(--ease-out);
}
.card:hover {
  border-color: var(--border-strong);
  transform: translateY(-2px);
  box-shadow: var(--shadow-soft);
}
.card__head {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}
.card__id {
  min-width: 0;
}
.card__name {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-strong);
}
.card__publisher {
  font-size: 13px;
  color: var(--text-muted);
}
.card__desc {
  color: var(--text-secondary);
  font-size: 14px;
  line-height: 1.6;
  min-height: 2.4em;
}
.card__caps {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  min-height: 24px;
}
.card__foot {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-top: auto;
  padding-top: var(--space-4);
  border-top: 1px solid var(--border);
  font-size: 13px;
  color: var(--text-secondary);
}
.card__version {
  font-weight: 600;
  color: var(--text);
}
.card__meta {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.card__go {
  margin-left: auto;
  color: var(--text-muted);
  transition: transform var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
}
.card:hover .card__go {
  color: var(--text-strong);
  transform: translateX(3px);
}
</style>
