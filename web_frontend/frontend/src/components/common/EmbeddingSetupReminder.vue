<template>
  <n-modal
    v-model:show="visible"
    preset="card"
    :bordered="false"
    :style="{ width: 'min(520px, calc(100vw - 32px))' }"
    :title="t('embeddingSetup.title')"
    @after-leave="rememberDismissal"
  >
    <div class="embedding-reminder">
      <p>{{ t('embeddingSetup.description') }}</p>
      <small>{{ t('embeddingSetup.fallback') }}</small>
    </div>
    <template #footer>
      <n-space justify="end">
        <n-button @click="dismiss">{{ t('embeddingSetup.later') }}</n-button>
        <n-button type="primary" @click="configure">{{ t('embeddingSetup.configure') }}</n-button>
      </n-space>
    </template>
  </n-modal>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { NButton, NModal, NSpace } from 'naive-ui'
import { useRouter } from 'vue-router'
import { modelPoolApi } from '@/api/modelPool'
import { useI18n } from '@/composables/useI18n'

const DISMISSAL_KEY = 'agentfactory.embedding-setup-reminder.v1'
const router = useRouter()
const { t } = useI18n()
const visible = ref(false)

onMounted(async () => {
  if (window.localStorage.getItem(DISMISSAL_KEY) === 'dismissed') return
  try {
    const response = await modelPoolApi.infrastructureBindings()
    visible.value = !response.bindings.embedding
  } catch {
    visible.value = false
  }
})

function rememberDismissal() {
  window.localStorage.setItem(DISMISSAL_KEY, 'dismissed')
}

function dismiss() {
  visible.value = false
  rememberDismissal()
}

async function configure() {
  visible.value = false
  rememberDismissal()
  await router.push({ name: 'ModelPool' })
}
</script>

<style scoped>
.embedding-reminder { display: grid; gap: 12px; }
.embedding-reminder p { margin: 0; color: var(--app-text); font-size: 14px; line-height: 1.7; }
.embedding-reminder small { color: var(--app-text-muted); font-size: 11px; line-height: 1.6; }
</style>
