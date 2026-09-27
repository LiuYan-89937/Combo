<template>
  <div class="agent-instructions-editor">
    <p class="field-description">{{ t('settings.agentInstructionsDescription') }}</p>
    <n-input
      v-model:value="content"
      type="textarea"
      :autosize="{ minRows: 5, maxRows: 12 }"
      :placeholder="t('settings.agentInstructionsPlaceholder')"
      :aria-label="t('settings.agentInstructions')"
    />
    <p v-if="error" class="editor-error" role="alert">{{ error }}</p>
    <div class="editor-actions">
      <n-button size="small" :loading="loading" @click="load">{{ t('common.refresh') }}</n-button>
      <n-button size="small" type="primary" :loading="saving" :disabled="loading || digest === null || content === savedContent" @click="save">
        {{ t('common.save') }}
      </n-button>
    </div>
    <div class="legacy-review">
      <n-button size="small" text :loading="reviewLoading" @click="toggleLegacyReview">
        {{ t('settings.legacyMemoryReview') }}
      </n-button>
      <template v-if="reviewVisible">
        <p class="field-description">{{ t('settings.legacyMemoryDescription') }}</p>
        <p v-if="reviewError" class="editor-error" role="alert">{{ reviewError }}</p>
        <p v-else-if="!reviewLoading && !legacyMemories.length" class="field-description">{{ t('settings.legacyMemoryEmpty') }}</p>
        <div v-else class="legacy-list">
          <article v-for="item in legacyMemories" :key="item.memory_id" class="legacy-item">
            <p>{{ item.content }}</p>
            <n-button size="small" secondary @click="addToDraft(item.content)">
              {{ t('settings.legacyMemoryAddToDraft') }}
            </n-button>
          </article>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { NButton, NInput } from 'naive-ui'
import { agentInstructionsApi } from '@/api/agentInstructions'
import { memoryApi, type LegacyUserMemoryView } from '@/api/memory'
import { useI18n } from '@/composables/useI18n'

const { t } = useI18n()
const content = ref('')
const savedContent = ref('')
const digest = ref<string | null>(null)
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const reviewVisible = ref(false)
const reviewLoading = ref(false)
const reviewError = ref('')
const legacyMemories = ref<LegacyUserMemoryView[]>([])

async function load() {
  loading.value = true
  try {
    const current = await agentInstructionsApi.read()
    content.value = current.content
    savedContent.value = current.content
    digest.value = current.digest
    error.value = ''
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    loading.value = false
  }
}

async function save() {
  if (digest.value === null || saving.value) return
  saving.value = true
  try {
    const updated = await agentInstructionsApi.replace(content.value, digest.value)
    digest.value = updated.digest
    savedContent.value = updated.content
    error.value = ''
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    saving.value = false
  }
}

async function toggleLegacyReview() {
  if (reviewVisible.value) {
    reviewVisible.value = false
    return
  }
  reviewVisible.value = true
  reviewLoading.value = true
  try {
    const response = await memoryApi.legacyUserMemories()
    legacyMemories.value = response.items
    reviewError.value = ''
  } catch (cause) {
    reviewError.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    reviewLoading.value = false
  }
}

function addToDraft(value: string) {
  content.value = [content.value.trimEnd(), value].filter(Boolean).join('\n\n')
}

onMounted(() => { void load() })
</script>

<style scoped>
.agent-instructions-editor { display: grid; gap: 10px; }
.editor-actions { display: flex; justify-content: flex-end; gap: 8px; }
.editor-error { color: var(--app-error); font-size: 12px; }
.legacy-review { display: grid; gap: 8px; }
.legacy-list { display: grid; gap: 8px; max-height: 260px; overflow-y: auto; }
.legacy-item { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.legacy-item p { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
