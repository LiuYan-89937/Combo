<template>
  <div class="memory-panel">
    <header>
      <strong>{{ t('status.memory') }}</strong>
      <div class="memory-controls">
        <n-select
          v-model:value="scope"
          class="memory-scope-select"
          size="small"
          :options="scopeOptions"
          :aria-label="t('status.memoryFilterLabel')"
          @update:value="refresh"
        />
        <n-button quaternary circle size="small" :loading="loading" @click="refresh">
          <template #icon><n-icon><RefreshOutline /></n-icon></template>
        </n-button>
      </div>
    </header>
    <div class="memory-search">
      <n-input v-model:value="query" size="small" clearable :placeholder="t('status.memoryQueryPlaceholder')" @keyup.enter="refresh" />
      <n-button secondary size="small" :loading="loading" @click="refresh">
        <template #icon><n-icon><SearchOutline /></n-icon></template>
      </n-button>
    </div>
    <p v-if="error" class="memory-error">{{ error }}</p>
    <n-spin :show="loading" size="small">
      <n-empty v-if="!items.length && !loading" :description="t('status.memoryEmpty')" size="small">
        <template #icon><ComboPngIcon name="empty-memory" :size="56" /></template>
      </n-empty>
      <div v-else class="memory-list">
        <article v-for="item in items" :key="item.memory_id" class="memory-item">
          <div class="memory-item-heading">
            <span>{{ memoryScopeLabel(item.source_scope) }}</span>
            <n-popconfirm
              :positive-text="t('common.delete')"
              :negative-text="t('common.cancel')"
              @positive-click="remove(item)"
            >
              <template #trigger>
                <n-button quaternary circle size="tiny" :loading="Boolean(deleting[item.memory_id])">
                  <template #icon><n-icon><TrashOutline /></n-icon></template>
                </n-button>
              </template>
              {{ t('status.memoryDeleteConfirm') }}
            </n-popconfirm>
          </div>
          <p>{{ item.content }}</p>
          <time v-if="item.updated_at">{{ formatTime(item.updated_at) }}</time>
        </article>
        <n-button v-if="nextOffset !== null" quaternary size="small" :loading="loading" @click="loadMore">
          {{ t('status.memoryLoadMore') }}
        </n-button>
      </div>
    </n-spin>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, watch } from 'vue'
import { NButton, NEmpty, NIcon, NInput, NPopconfirm, NSelect, NSpin } from 'naive-ui'
import { RefreshOutline, SearchOutline, TrashOutline } from '@/components/icons'
import ComboPngIcon from '@/components/icons/ComboPngIcon.vue'
import { memoryApi, type MemoryContextItemView, type MemoryScopeFilter } from '@/api/memory'
import { useI18n } from '@/composables/useI18n'
import { formatShortDateTime, parseDate } from '@/utils/format'

const { t } = useI18n()
const props = defineProps<{ workspaceId?: string | null }>()
const query = ref('')
const scope = ref<MemoryScopeFilter>('all')
const scopeOptions = computed(() => [
  { label: t('status.memoryScope.all'), value: 'all' },
  { label: t('status.memoryScope.user'), value: 'user' },
  { label: t('status.memoryScope.workspace'), value: 'workspace', disabled: !props.workspaceId },
])
const items = ref<MemoryContextItemView[]>([])
const loading = ref(false)
const error = ref('')
const deleting = ref<Record<string, boolean>>({})
const nextOffset = ref<number | null>(null)
let requestSerial = 0

async function loadPage(offset: number, append: boolean) {
  const serial = ++requestSerial
  loading.value = true
  error.value = ''
  try {
    const response = await memoryApi.query(query.value.trim(), offset, scope.value, props.workspaceId || null)
    if (serial === requestSerial) {
      items.value = [...(append ? items.value : []), ...(response.items || [])].sort(memorySort)
      nextOffset.value = response.next_offset
    }
  } catch (cause) {
    if (serial === requestSerial) {
      if (!append) {
        items.value = []
        nextOffset.value = null
      }
      error.value = cause instanceof Error ? cause.message : String(cause)
    }
  } finally {
    if (serial === requestSerial) loading.value = false
  }
}

function refresh() { return loadPage(0, false) }
function loadMore() {
  if (nextOffset.value !== null) void loadPage(nextOffset.value, true)
}

async function remove(item: MemoryContextItemView) {
  deleting.value = { ...deleting.value, [item.memory_id]: true }
  try {
    await memoryApi.deleteItem(item.memory_id)
    await refresh()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    const next = { ...deleting.value }
    delete next[item.memory_id]
    deleting.value = next
  }
}

function memorySort(left: MemoryContextItemView, right: MemoryContextItemView): number {
  return Number(right.score || 0) - Number(left.score || 0)
    || String(right.updated_at || '').localeCompare(String(left.updated_at || ''))
}

function memoryScopeLabel(scope: string): string {
  if (scope === 'workspace') return t('status.memoryScope.workspace')
  return t('status.memoryScope.user')
}

function formatTime(value: string): string {
  const parsed = parseDate(value)
  return parsed ? formatShortDateTime(parsed) : value
}

onMounted(() => { void refresh() })
watch(() => props.workspaceId, () => {
  if (scope.value === 'workspace') {
    if (!props.workspaceId) scope.value = 'all'
    void refresh()
  }
})
</script>

<style scoped>
.memory-panel { width: min(390px, calc(100vw - 44px)); max-height: min(64vh, 560px); display: flex; flex-direction: column; padding: 14px; }
header, .memory-controls, .memory-item-heading, .memory-search { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
header { margin-bottom: 12px; }
header strong { font-size: 13px; }
.memory-search { margin-bottom: 12px; }
.memory-search :deep(.n-input) { flex: 1; }
.memory-scope-select { width: 104px; }
.memory-list { display: grid; max-height: 430px; overflow: auto; gap: 8px; padding-right: 3px; }
.memory-item { padding: 10px 11px; border: 1px solid var(--app-border); border-radius: var(--app-radius-md); background: var(--app-surface); }
.memory-item-heading span { color: var(--app-text-muted); font-size: 10px; }
.memory-item p { margin: 6px 0; font-size: 11px; line-height: 1.5; }
.memory-item time { color: var(--app-text-subtle); font-size: 9px; }
.memory-error { color: var(--app-error); font-size: 11px; }
</style>
