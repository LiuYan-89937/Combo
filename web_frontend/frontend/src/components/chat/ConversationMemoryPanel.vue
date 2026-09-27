<template>
  <div class="recalled-memory-panel">
    <header>
      <strong>{{ t('status.memoryRecalled') }}</strong>
      <n-button quaternary circle size="small" :loading="loading" :aria-label="t('status.memoryRefresh')" @click="refresh">
        <template #icon><n-icon><RefreshOutline /></n-icon></template>
      </n-button>
    </header>
    <p v-if="error" class="memory-error">{{ error }}</p>
    <n-empty v-else-if="!loading && !items.length" :description="t('status.memoryRecalledEmpty')" size="small" />
    <div v-else class="recalled-memory-list">
      <article v-for="item in items" :key="`${item.memory_id}:${item.revision}`" class="recalled-memory-item">
        <span>{{ item.source_scope === 'workspace' ? t('status.memoryScope.workspace') : t('status.memoryScope.session') }}</span>
        <p>{{ item.content }}</p>
      </article>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { NButton, NEmpty, NIcon } from 'naive-ui'
import { RefreshOutline } from '@/components/icons'
import { memoryApi, type RecalledMemoryView } from '@/api/memory'
import { useI18n } from '@/composables/useI18n'

const props = defineProps<{ sessionId?: string | null; visible: boolean }>()
const { t } = useI18n()
const items = ref<RecalledMemoryView[]>([])
const loading = ref(false)
const error = ref('')
let requestSerial = 0
let refreshTimer: ReturnType<typeof setInterval> | null = null

async function refresh() {
  const sessionId = props.sessionId
  const serial = ++requestSerial
  if (!sessionId) {
    items.value = []
    return
  }
  loading.value = true
  try {
    const response = await memoryApi.recalled(sessionId)
    if (serial === requestSerial) {
      items.value = response.items
      error.value = ''
    }
  } catch (cause) {
    if (serial === requestSerial) error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    if (serial === requestSerial) loading.value = false
  }
}

watch(() => [props.sessionId, props.visible], () => {
  requestSerial += 1
  if (refreshTimer) clearInterval(refreshTimer)
  refreshTimer = null
  items.value = []
  error.value = ''
  loading.value = false
  if (props.visible && props.sessionId) {
    void refresh()
    refreshTimer = setInterval(() => { if (!loading.value) void refresh() }, 3000)
  }
}, { immediate: true })
onBeforeUnmount(() => { if (refreshTimer) clearInterval(refreshTimer) })
</script>

<style scoped>
.recalled-memory-panel { width: min(350px, calc(100vw - 44px)); max-height: min(60vh, 460px); display: flex; flex-direction: column; padding: 13px; }
header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 9px; }
header strong { font-size: 13px; }
.recalled-memory-list { display: grid; gap: 7px; overflow: auto; }
.recalled-memory-item { padding: 9px 10px; border: 1px solid var(--app-border); border-radius: var(--app-radius-md); }
.recalled-memory-item span { color: var(--app-text-muted); font-size: 10px; }
.recalled-memory-item p { margin: 5px 0 0; font-size: 11px; line-height: 1.55; white-space: pre-wrap; overflow-wrap: anywhere; }
.memory-error { color: var(--app-error); font-size: 11px; }
</style>
