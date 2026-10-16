<template>
  <div class="memory-panel">
    <header>
      <strong>{{ t('status.memory') }}</strong>
      <div class="memory-controls">
        <n-button size="small" secondary :disabled="!canMerge" @click="openEditor('merge')">{{ t('memoryManagement.merge') }}</n-button>
        <n-button size="small" secondary @click="openEditor('create')">{{ t('memoryManagement.create') }}</n-button>
        <n-button quaternary circle size="small" :loading="loading" :aria-label="t('common.refresh')" @click="refresh">
          <template #icon><n-icon><RefreshOutline /></n-icon></template>
        </n-button>
      </div>
    </header>
    <div class="memory-search">
      <n-input v-model:value="query" size="small" clearable :placeholder="t('status.memoryQueryPlaceholder')" @keyup.enter="refresh" />
      <n-button secondary size="small" :loading="loading" :aria-label="t('status.memoryQueryPlaceholder')" @click="refresh">
        <template #icon><n-icon><SearchOutline /></n-icon></template>
      </n-button>
    </div>
    <p v-if="error" class="memory-error" role="alert">{{ error }}</p>
    <n-spin :show="loading" size="small">
      <n-empty v-if="!items.length && !loading" :description="t('status.memoryEmpty')" size="small">
        <template #icon><ComboPngIcon name="empty-memory" :size="56" /></template>
      </n-empty>
      <div v-else class="memory-list">
        <article v-for="item in items" :key="item.memory_id" class="memory-item">
          <div class="memory-item-heading">
            <n-checkbox :checked="selectedIds.includes(item.memory_id)" @update:checked="toggleSelection(item.memory_id, $event)">
              {{ kindLabel(item.kind) }}
            </n-checkbox>
            <div class="memory-controls">
              <n-button quaternary size="tiny" @click="openEditor('edit', item)">{{ t('common.edit') }}</n-button>
              <n-popconfirm :positive-text="t('common.delete')" :negative-text="t('common.cancel')" @positive-click="remove(item)">
                <template #trigger>
                  <n-button quaternary circle size="tiny" :aria-label="t('common.delete')" :loading="Boolean(deleting[item.memory_id])">
                    <template #icon><n-icon><TrashOutline /></n-icon></template>
                  </n-button>
                </template>
                {{ t('status.memoryDeleteConfirm') }}
              </n-popconfirm>
            </div>
          </div>
          <p>{{ item.content }}</p>
          <time v-if="item.updated_at">{{ formatTime(item.updated_at) }}</time>
        </article>
        <n-button v-if="nextOffset !== null" quaternary size="small" :loading="loading" @click="loadMore">{{ t('status.memoryLoadMore') }}</n-button>
      </div>
    </n-spin>
    <n-modal :show="editorMode !== null" @update:show="closeEditor">
      <n-card class="memory-editor" :title="editorTitle" :bordered="false" role="dialog" aria-modal="true">
        <n-form label-placement="top">
          <n-form-item :label="t('memoryManagement.kind')">
            <n-select v-model:value="draftKind" :options="kindOptions" :disabled="editorMode === 'merge'" />
          </n-form-item>
          <p class="memory-guidance">{{ t(`memoryManagement.kindHelp.${draftKind}`) }}</p>
          <n-form-item :label="t('memoryManagement.content')">
            <n-input v-model:value="draftContent" type="textarea" :autosize="{ minRows: 3, maxRows: 8 }" />
          </n-form-item>
          <p class="memory-guidance" :class="{ 'memory-error': contentLength > MEMORY_CONTENT_MAX_CHARS }">{{ contentLength }} / {{ MEMORY_CONTENT_MAX_CHARS }}</p>
          <p v-if="editorError" class="memory-error" role="alert">{{ editorError }}</p>
        </n-form>
        <template #footer>
          <div class="editor-actions">
            <n-button :disabled="saving" @click="closeEditor">{{ t('common.cancel') }}</n-button>
            <n-button type="primary" :loading="saving" :disabled="!contentLength || contentLength > MEMORY_CONTENT_MAX_CHARS" @click="save">{{ t('common.save') }}</n-button>
          </div>
        </template>
      </n-card>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, watch } from 'vue'
import { NButton, NCard, NCheckbox, NEmpty, NForm, NFormItem, NIcon, NInput, NModal, NPopconfirm, NSelect, NSpin } from 'naive-ui'
import { RefreshOutline, SearchOutline, TrashOutline } from '@/components/icons'
import ComboPngIcon from '@/components/icons/ComboPngIcon.vue'
import { MEMORY_CONTENT_MAX_CHARS, memoryApi, type MemoryContextItemView, type MemoryKind, type MemoryDraft } from '@/api/memory'
import { useI18n } from '@/composables/useI18n'
import { formatShortDateTime, parseDate } from '@/utils/format'

const { t } = useI18n()
const props = defineProps<{ workspaceId: string | null; sessionId: string | null; scope: 'workspace' | 'session' }>()
const query = ref('')
const items = ref<MemoryContextItemView[]>([])
const loading = ref(false)
const error = ref('')
const deleting = ref<Record<string, boolean>>({})
const nextOffset = ref<number | null>(null)
const selectedIds = ref<string[]>([])
const selectedItems = computed(() => items.value.filter(item => selectedIds.value.includes(item.memory_id)))
const canMerge = computed(() => selectedItems.value.length >= 2 && selectedItems.value.every(item => item.kind === selectedItems.value[0].kind))
const editorMode = ref<'create' | 'edit' | 'merge' | null>(null)
const editedItem = ref<MemoryContextItemView | null>(null)
const draftKind = ref<MemoryKind>('fact')
const draftContent = ref('')
const editorError = ref('')
const saving = ref(false)
const contentLength = computed(() => Array.from(draftContent.value.trim()).length)
const editorTitle = computed(() => t(`memoryManagement.${editorMode.value === 'edit' ? 'edit' : editorMode.value === 'merge' ? 'merge' : 'create'}`))
const kinds: MemoryKind[] = ['constraint', 'preference', 'decision', 'fact', 'artifact']
const kindOptions = computed(() => kinds.map(kind => ({ label: kindLabel(kind), value: kind })))
let requestSerial = 0

async function loadPage(offset: number, append: boolean) {
  const serial = ++requestSerial
  loading.value = true
  error.value = ''
  try {
    if (!props.workspaceId || (props.scope === 'session' && !props.sessionId)) {
      items.value = []
      nextOffset.value = null
      return
    }
    const response = await memoryApi.query(query.value.trim(), offset, props.scope, props.workspaceId, props.sessionId)
    if (serial === requestSerial) {
      items.value = [...(append ? items.value : []), ...response.items].sort(memorySort)
      nextOffset.value = response.next_offset
      if (!append) selectedIds.value = []
    }
  } catch (cause) {
    if (serial === requestSerial) {
      if (!append) items.value = []
      error.value = cause instanceof Error ? cause.message : String(cause)
    }
  } finally {
    if (serial === requestSerial) loading.value = false
  }
}

function refresh() { return loadPage(0, false) }
function loadMore() { if (nextOffset.value !== null) void loadPage(nextOffset.value, true) }
function toggleSelection(id: string, checked: boolean) {
  selectedIds.value = checked ? [...selectedIds.value, id] : selectedIds.value.filter(value => value !== id)
}
function openEditor(mode: 'create' | 'edit' | 'merge', item?: MemoryContextItemView) {
  editorMode.value = mode
  editedItem.value = item || null
  draftKind.value = item?.kind || (mode === 'merge' ? selectedItems.value[0].kind : 'fact')
  draftContent.value = item?.content || ''
  editorError.value = ''
}
function closeEditor() { if (!saving.value) editorMode.value = null }
async function save() {
  if (!props.workspaceId) return
  const draft: MemoryDraft = { workspace_id: props.workspaceId, session_id: props.scope === 'session' ? props.sessionId : null,
    scope: props.scope, kind: draftKind.value, content: draftContent.value.trim() }
  saving.value = true
  editorError.value = ''
  try {
    if (editorMode.value === 'edit' && editedItem.value) await memoryApi.updateItem(editedItem.value, draft)
    else if (editorMode.value === 'merge') await memoryApi.mergeItems(selectedItems.value, draft)
    else await memoryApi.createItem(draft)
    editorMode.value = null
    await refresh()
  } catch (cause) {
    editorError.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    saving.value = false
  }
}
async function remove(item: MemoryContextItemView) {
  if (!props.workspaceId || (props.scope === 'session' && !props.sessionId)) return
  deleting.value = { ...deleting.value, [item.memory_id]: true }
  try {
    await memoryApi.deleteItem(item.memory_id, props.workspaceId, props.scope === 'session' ? props.sessionId : null)
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
  return right.score - left.score || String(right.updated_at || '').localeCompare(String(left.updated_at || ''))
}
function kindLabel(kind: MemoryKind) { return t(`memoryManagement.kind.${kind}`) }
function formatTime(value: string): string {
  const parsed = parseDate(value)
  return parsed ? formatShortDateTime(parsed) : value
}
onMounted(() => { void refresh() })
watch(() => [props.workspaceId, props.sessionId, props.scope], () => { editorMode.value = null; void refresh() })
</script>

<style scoped>
.memory-panel { width: 100%; display: flex; flex-direction: column; padding: 14px; }
header, .memory-controls, .memory-item-heading, .memory-search, .editor-actions { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
header { margin-bottom: 12px; }
header strong { font-size: 13px; }
.memory-search { margin-bottom: 12px; }
.memory-search :deep(.n-input) { flex: 1; }
.memory-list { display: grid; gap: 8px; padding-right: 3px; }
.memory-item { padding: 10px 11px; border: 1px solid var(--app-border); border-radius: var(--app-radius-md); background: var(--app-surface); }
.memory-item p { margin: 6px 0; font-size: 12px; line-height: 1.6; overflow-wrap: anywhere; }
.memory-item time, .memory-guidance { color: var(--app-text-subtle); font-size: 11px; }
.memory-error { color: var(--app-error); font-size: 12px; }
.memory-editor { width: min(460px, calc(100vw - 32px)); border-radius: var(--app-radius-lg); }
.editor-actions { justify-content: flex-end; }
</style>
