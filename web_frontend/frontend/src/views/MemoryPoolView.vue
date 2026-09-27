<template>
  <main class="memory-page">
    <header class="page-header">
      <div>
        <span class="eyebrow">MEMORY</span>
        <h1>{{ t('memoryManagement.title') }}</h1>
      </div>
      <n-button secondary @click="router.back()">{{ t('common.back') }}</n-button>
    </header>

    <section class="memory-surface">
      <n-radio-group v-model:value="scope" size="small" class="soft-segmented-control">
        <n-radio-button value="workspace">{{ t('status.memoryScope.workspace') }}</n-radio-button>
        <n-radio-button value="session">{{ t('memoryManagement.session') }}</n-radio-button>
      </n-radio-group>

      <p v-if="error" class="scope-error">{{ error }}</p>
      <n-spin v-if="loading" size="small" />
      <template v-else>
        <div class="scope-selectors">
          <n-select
            v-if="scope === 'workspace'"
            v-model:value="workspaceId"
            :options="workspaceOptions"
            :placeholder="t('memoryManagement.chooseWorkspace')"
            :aria-label="t('memoryManagement.chooseWorkspace')"
          />
          <n-select
            v-else
            v-model:value="sessionId"
            :options="sessionOptions"
            :placeholder="t('memoryManagement.chooseSession')"
            :aria-label="t('memoryManagement.chooseSession')"
          />
        </div>
        <SavedMemoryPanel
          v-if="selectedWorkspaceId"
          :key="`${scope}:${selectedWorkspaceId}:${sessionId}`"
          :workspace-id="selectedWorkspaceId"
          :session-id="scope === 'session' ? sessionId : null"
          :scope="scope"
        />
        <n-empty v-else :description="t('memoryManagement.emptyScope')" />
      </template>
    </section>
  </main>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NEmpty, NRadioButton, NRadioGroup, NSelect, NSpin } from 'naive-ui'
import SavedMemoryPanel from '@/components/common/SavedMemoryPanel.vue'
import { memoryApi, type MemoryScopesResponse } from '@/api/memory'
import { useI18n } from '@/composables/useI18n'

const router = useRouter()
const { t } = useI18n()
const scope = ref<'workspace' | 'session'>('workspace')
const workspaceId = ref<string | null>(null)
const sessionId = ref<string | null>(null)
const scopes = ref<MemoryScopesResponse>({ workspaces: [], sessions: [] })
const loading = ref(true)
const error = ref('')
const workspaceOptions = computed(() => scopes.value.workspaces.map(item => ({ label: item.title, value: item.workspace_id })))
const sessionOptions = computed(() => scopes.value.sessions
  .map(item => ({ label: item.title, value: item.session_id })))
const selectedWorkspaceId = computed(() => scope.value === 'workspace'
  ? workspaceId.value
  : scopes.value.sessions.find(item => item.session_id === sessionId.value)?.workspace_id || null)

onMounted(async () => {
  try {
    scopes.value = await memoryApi.scopes()
    workspaceId.value = workspaceOptions.value[0]?.value || null
    sessionId.value = sessionOptions.value[0]?.value || null
    if (!workspaceId.value) scope.value = 'session'
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.memory-page { width: min(900px, calc(100% - 40px)); margin: 30px auto; color: var(--app-text); }
.page-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 24px; }
.page-header h1 { margin: 4px 0 0; font-size: 25px; }
.eyebrow { font-size: 10px; letter-spacing: .14em; color: var(--app-text-muted); }
.memory-surface { padding: 20px; border: 1px solid var(--app-border); border-radius: var(--app-radius-lg); background: var(--app-surface); }
.scope-selectors { display: flex; gap: 10px; margin-top: 18px; }
.scope-selectors :deep(.n-select) { width: min(280px, 100%); }
.scope-error { color: var(--app-error); }
@media (max-width: 640px) { .scope-selectors { flex-direction: column; } .scope-selectors :deep(.n-select) { width: 100%; } }
</style>
