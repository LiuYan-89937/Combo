<template>
  <section v-if="pending" class="question-panel">
    <div class="question-header">
      <div class="question-title">
        <ComboMascot state="waiting" :size="52" />
        <span>{{ t('chat.childQuestionTitle') }}</span>
      </div>
      <n-tag v-if="sourceTaskName" size="small" :bordered="false">
        {{ sourceTaskName }}
      </n-tag>
    </div>

    <p class="question-message">{{ questionMessage }}</p>

    <div v-if="choices.length" class="question-options">
      <button
        v-for="option in choices"
        :key="option.value"
        type="button"
        :class="{ selected: selectedOption === option.value }"
        @click="selectOption(option.value)"
      >
        <strong>{{ option.label }}</strong>
        <small v-if="option.description">{{ option.description }}</small>
      </button>
    </div>

    <n-input
      v-if="allowFreeText"
      v-model:value="answerText"
      type="textarea"
      :autosize="{ minRows: 2, maxRows: 5 }"
      :placeholder="t('backgroundTask.responsePlaceholder')"
      @update:value="selectedOption = ''"
    />

    <div class="question-actions">
      <n-button
        type="primary"
        size="small"
        :loading="submitting"
        :disabled="!answer"
        @click="submit"
      >
        {{ t('backgroundTask.submitResponse') }}
      </n-button>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { NButton, NInput, NTag } from 'naive-ui'
import ComboMascot from '@/components/brand/ComboMascot.vue'
import { useCommand } from '@/composables/useCommand'
import { useI18n } from '@/composables/useI18n'
import { useRuntimeStore } from '@/stores/runtime'

interface QuestionChoice {
  value: string
  label: string
  description?: string
}

const runtimeStore = useRuntimeStore()
const commands = useCommand()
const { t } = useI18n()
const answerText = ref('')
const selectedOption = ref('')
const submitting = ref(false)

const pending = computed(() => runtimeStore.pendingInterrupt)
const sourceTaskName = computed(() => String(pending.value?.payload?.source_task_name || '').trim())
const questionMessage = computed(() => String(
  pending.value?.payload?.message
  || pending.value?.payload?.prompt
  || t('backgroundTask.pendingInput'),
).trim())
const choices = computed<QuestionChoice[]>(() => {
  const raw = pending.value?.payload?.choices
  if (!Array.isArray(raw)) return []
  return raw.flatMap((item): QuestionChoice[] => {
    if (!item || typeof item !== 'object') return []
    const value = String((item as any).value || '').trim()
    const label = String((item as any).label || value).trim()
    if (!value || !label) return []
    const description = String((item as any).description || '').trim()
    return [{ value, label, ...(description ? { description } : {}) }]
  })
})
const allowFreeText = computed(() => pending.value?.payload?.allow_free_text !== false)
const answer = computed(() => answerText.value.trim() || selectedOption.value)

function selectOption(value: string) {
  selectedOption.value = value
  answerText.value = ''
}

function submit() {
  if (!pending.value || !answer.value || submitting.value) return
  submitting.value = true
  commands.answerInterrupt(answer.value)
}
</script>

<style scoped>
.question-panel {
  padding: 18px;
  border: 1px solid var(--app-border);
  border-radius: 20px;
  background: var(--app-surface);
  color: var(--app-text);
  animation: app-fade-in-up 0.28s cubic-bezier(0.16, 1, 0.3, 1) both;
}

.question-header,
.question-title,
.question-actions {
  display: flex;
  align-items: center;
}

.question-header {
  justify-content: space-between;
  gap: 12px;
}

.question-title {
  gap: 10px;
  font-size: 15px;
  font-weight: 600;
}

.question-message {
  margin: 14px 0;
  line-height: 1.55;
  white-space: pre-wrap;
}

.question-options {
  display: grid;
  gap: 8px;
  margin-bottom: 12px;
}

.question-options button {
  display: grid;
  gap: 3px;
  padding: 10px 12px;
  border: 1px solid var(--app-border);
  border-radius: 12px;
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
}

.question-options button.selected {
  border-color: var(--app-primary);
  background: color-mix(in srgb, var(--app-primary) 9%, transparent);
}

.question-options small {
  color: var(--app-text-muted);
}

.question-actions {
  justify-content: flex-end;
  margin-top: 12px;
}
</style>
