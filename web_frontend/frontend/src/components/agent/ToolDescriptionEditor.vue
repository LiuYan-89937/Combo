<template>
  <div class="tool-description-editor">
    <n-input
      :value="modelValue"
      type="textarea"
      :autosize="{ minRows: 2, maxRows: 6 }"
      placeholder="填写工具用途、适用时机、输入要求和能力边界"
      @update:value="emit('update:modelValue', $event)"
    />
    <div v-if="error" class="tool-description-error">{{ error }}</div>
    <div class="tool-description-actions">
      <n-button
        size="tiny"
        type="primary"
        :loading="saving"
        :disabled="!dirty"
        @click="emit('save')"
      >
        {{ t('common.save') }}
      </n-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { NButton, NInput } from 'naive-ui'
import { useI18n } from '@/composables/useI18n'

defineProps<{
  modelValue: string
  dirty: boolean
  saving: boolean
  error?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
  save: []
}>()

const { t } = useI18n()
</script>

<style scoped>
.tool-description-editor {
  display: grid;
  gap: 6px;
  margin-top: 8px;
}

.tool-description-actions {
  display: flex;
  justify-content: flex-end;
}

.tool-description-error {
  color: var(--n-color-error, #d03050);
  font-size: 12px;
  line-height: 1.4;
}
</style>
