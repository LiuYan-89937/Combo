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
        <n-button size="small" type="primary" @click="handleConfirmPublish">
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
import { CheckmarkCircle, CreateOutline, RocketOutline } from '@/components/icons'
import { useCommand } from '@/composables/useCommand'
import { useI18n } from '@/composables/useI18n'
import { useRuntimeStore } from '@/stores/runtime'

const runtimeStore = useRuntimeStore()
const commands = useCommand()
const { t } = useI18n()
const revisionGuidance = ref('')

const payload = computed(() => runtimeStore.publishConfirmationPayload || {})
const messageText = computed(() => String(payload.value.message || t('publish.defaultMessage')))
const validationLabel = computed(() => {
  const validation = payload.value.validation
  if (!validation || typeof validation !== 'object') return t('publish.ready')
  const scope = String(validation.validation_scope || '').trim()
  const status = String(validation.status || '').trim()
  return [scope, status].filter(Boolean).join(' / ') || t('publish.ready')
})

function handleConfirmPublish() {
  commands.confirmPublish()
}

function handleContinueRevision() {
  const guidance = revisionGuidance.value.trim()
  if (!guidance) return
  commands.continuePublishRevision(guidance)
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

.revision-row {
  margin-top: 14px;
}

.publish-actions {
  margin-top: 12px;
}
</style>
