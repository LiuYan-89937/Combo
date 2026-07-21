<template>
  <section class="publish-confirmation-panel">
    <div class="publish-header">
      <div class="publish-title">
        <n-icon size="18">
          <RocketOutline />
        </n-icon>
        <span>{{ t('publish.title') }}</span>
      </div>
      <n-tag size="small" type="success" :bordered="false">
        {{ validationLabel }}
      </n-tag>
    </div>

    <p class="publish-message">
      {{ messageText }}
    </p>

    <div v-if="pendingResources.length" class="publish-resource-notice">
      <strong>发布后待配置 Resource</strong>
      <span>{{ pendingResources.map(item => item.resource_id).join('、') }}</span>
      <small>这些配置不阻断发布；对应工具在包详情中完成配置前不可执行。</small>
    </div>

    <div class="revision-row">
      <n-input
        v-model:value="revisionGuidance"
        type="textarea"
        size="small"
        :placeholder="t('publish.revisionPlaceholder')"
        :autosize="{ minRows: 2, maxRows: 4 }"
      />
    </div>

    <div class="publish-actions">
      <n-space justify="end" :wrap="true">
        <n-button
          size="small"
          :disabled="!revisionGuidance.trim()"
          @click="handleContinueRevision"
        >
          <template #icon>
            <n-icon><CreateOutline /></n-icon>
          </template>
          {{ t('publish.continueRevision') }}
        </n-button>
        <n-button
          size="small"
          type="primary"
          :loading="publishSubmitting"
          @click="handleConfirmPublish"
        >
          <template #icon>
            <n-icon><CheckmarkCircle /></n-icon>
          </template>
          {{ t('publish.confirm') }}
        </n-button>
      </n-space>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { NButton, NIcon, NInput, NSpace, NTag } from 'naive-ui'
import { createAgentApi } from '@/api/createAgent'
import { CheckmarkCircle, CreateOutline, RocketOutline } from '@/components/icons'
import { useCommand } from '@/composables/useCommand'
import { useI18n } from '@/composables/useI18n'
import { useRuntimeStore } from '@/stores/runtime'
import { useUiStore } from '@/stores/ui'

const runtimeStore = useRuntimeStore()
const commands = useCommand()
const uiStore = useUiStore()
const { t } = useI18n()
const revisionGuidance = ref('')
const publishSubmitting = ref(false)

const payload = computed(() => runtimeStore.publishConfirmationPayload || {})
const messageText = computed(() => String(payload.value.message || t('publish.defaultMessage')))
const pendingResources = computed<Array<{ resource_id: string }>>(() => {
  const values = payload.value.runtime_configuration?.pending_resources
  if (!Array.isArray(values)) return []
  return values.filter((item): item is { resource_id: string } => Boolean(item && typeof item.resource_id === 'string'))
})
const validationLabel = computed(() => {
  const validation = payload.value.validation
  if (!validation || typeof validation !== 'object') return t('publish.ready')
  const scope = String(validation.validation_scope || '').trim()
  const status = String(validation.status || '').trim()
  return [scope, status].filter(Boolean).join(' / ') || t('publish.ready')
})

async function handleConfirmPublish() {
  if (publishSubmitting.value) return
  const workspaceId = String(payload.value.workspace_id || '').trim()
  if (!workspaceId) {
    uiStore.addNotification({
      type: 'error',
      title: t('publish.failedTitle'),
      message: t('publish.missingSession'),
      duration: 3500,
    })
    return
  }
  publishSubmitting.value = true
  try {
    await createAgentApi.publish(workspaceId)
    runtimeStore.clearCreateAgentPublishReady()
    commands.listAgentPackages()
    uiStore.addNotification({
      type: 'success',
      title: t('publish.successTitle'),
      message: t('publish.successMessage'),
      duration: 3000,
    })
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    uiStore.addNotification({
      type: 'error',
      title: t('publish.failedTitle'),
      message,
      duration: 5000,
    })
  } finally {
    publishSubmitting.value = false
  }
}

function handleContinueRevision() {
  const guidance = revisionGuidance.value.trim()
  if (!guidance) return
  runtimeStore.clearCreateAgentPublishReady()
  commands.sendMessage(guidance, 'create_agent')
  revisionGuidance.value = ''
}
</script>

<style scoped>
.publish-confirmation-panel {
  padding: var(--app-space-lg);
  border: 1px solid var(--app-text);
  border-radius: var(--app-radius-lg);
  background: var(--app-surface);
  color: var(--app-text);
  box-shadow: var(--app-shadow-md);
  animation: app-fade-in-up 0.28s cubic-bezier(0.16, 1, 0.3, 1) both;
  position: relative;
}

.publish-confirmation-panel::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  border-radius: var(--app-radius-lg) 0 0 var(--app-radius-lg);
  background: var(--app-success);
  animation: app-pulse-soft 1.6s ease-in-out infinite;
}

.publish-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.publish-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
}

.publish-message {
  margin: 12px 0 0;
  color: var(--app-text-secondary);
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
}

.publish-resource-notice {
  margin-top: 12px;
  display: grid;
  gap: 4px;
  padding: 10px 12px;
  border: 1px solid var(--app-warning);
  border-radius: var(--app-radius-md);
  background: var(--app-surface-muted);
  color: var(--app-text-secondary);
  font-size: 12px;
}

.publish-resource-notice strong { color: var(--app-text); }
.publish-resource-notice small { color: var(--app-text-muted); line-height: 1.5; }

.revision-row {
  margin-top: 14px;
}

.publish-actions {
  margin-top: 12px;
}
</style>
