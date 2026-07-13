<template>
  <section class="resource-request-panel">
    <div class="resource-request-title">需要运行时资源配置</div>
    <div v-for="request in requests" :key="request.resource_id" class="resource-request-row">
      <div class="resource-request-copy">
        <strong>{{ request.resource_id }}</strong>
        <span>{{ request.description || '此能力需要运行时资源后才能使用。' }}</span>
      </div>
      <n-input
        v-model:value="drafts[request.resource_id]"
        :type="request.secret ? 'password' : 'textarea'"
        :show-password-on="request.secret ? 'click' : undefined"
        :placeholder="request.secret ? '安全填写后保存' : '填写 JSON 值或普通文本'"
      />
      <div class="resource-request-actions">
        <n-button type="primary" size="small" :loading="saving === request.resource_id" @click="save(request)">保存并继续</n-button>
        <n-button size="small" quaternary :disabled="saving !== ''" @click="$emit('skip')">稍后配置</n-button>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { NButton, NInput } from 'naive-ui'
import { createAgentApi } from '@/api/createAgent'

interface ResourceRequestView {
  resource_id: string
  description?: string
  secret?: boolean
}

const props = defineProps<{ sessionId: string; requests: ResourceRequestView[] }>()
const emit = defineEmits<{ configured: [resourceId: string]; skip: [] }>()
const drafts = ref<Record<string, string>>({})
const saving = ref('')

async function save(request: ResourceRequestView) {
  const raw = drafts.value[request.resource_id] || ''
  let value: unknown = raw
  try { value = JSON.parse(raw) } catch { /* A scalar string is valid when the descriptor permits it. */ }
  saving.value = request.resource_id
  try {
    await createAgentApi.putResource(props.sessionId, request.resource_id, value)
    drafts.value[request.resource_id] = ''
    emit('configured', request.resource_id)
  } finally {
    saving.value = ''
  }
}
</script>

<style scoped>
.resource-request-panel { border-top: 1px solid var(--app-border); padding: var(--app-space-md); display: grid; gap: var(--app-space-sm); background: var(--app-surface); }
.resource-request-title { width: min(100%, 920px); margin: 0 auto; font-weight: 600; }
.resource-request-row { width: min(100%, 920px); margin: 0 auto; display: grid; gap: var(--app-space-sm); padding: var(--app-space-sm); border: 1px solid var(--app-border); border-radius: var(--app-radius-md); }
.resource-request-copy { display: grid; gap: 2px; font-size: 13px; }
.resource-request-copy span { color: var(--app-text-muted); }
.resource-request-actions { display: flex; justify-content: flex-end; gap: var(--app-space-xs); }
</style>
