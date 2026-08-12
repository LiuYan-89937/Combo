<template>
  <section class="dependency-progress" :class="`is-${status}`" role="status" aria-live="polite">
    <div class="progress-mascot" aria-hidden="true">
      <ComboFrameAnimation
        :character="status === 'running' ? 'companion' : 'paired'"
        :action="status === 'running' ? 'idle' : status === 'succeeded' ? 'complete' : 'error'"
        :size="58"
      />
    </div>
    <div class="progress-content">
      <div class="progress-heading">
        <div>
          <strong>{{ heading }}</strong>
          <span>{{ stageLabel }}</span>
        </div>
        <small>{{ progressCounter }}</small>
      </div>
      <n-progress
        type="line"
        :percentage="percentage"
        :show-indicator="false"
        :processing="status === 'running'"
        color="var(--app-text)"
        rail-color="var(--app-divider)"
      />
      <div v-if="requirements.length" class="requirement-list">
        <span v-for="requirement in requirements" :key="requirement">{{ requirement }}</span>
      </div>
      <details v-if="logs.length" class="progress-logs" :open="status === 'failed'">
        <summary>{{ t('toolPreparation.logs') }} · {{ logs.length }}</summary>
        <pre>{{ logs.join('\n') }}</pre>
      </details>
      <p v-if="error" class="progress-error">{{ error }}</p>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NProgress } from 'naive-ui'
import ComboFrameAnimation from '@/components/brand/ComboFrameAnimation.vue'
import { useI18n } from '@/composables/useI18n'

type PreparationStatus = 'running' | 'succeeded' | 'failed'

const props = withDefaults(defineProps<{
  status: PreparationStatus
  stage: string
  logs?: string[]
  requirements?: string[]
  error?: string
}>(), {
  logs: () => [],
  requirements: () => [],
  error: '',
})

const { t } = useI18n()
const orderedStages = [
  'uploading_tool_package',
  'assembling_tool_package',
  'validating_tool_package',
  'waiting_for_dependency_profile',
  'checking_dependency_profile',
  'creating_python_build_environment',
  'building_python_wheels',
  'storing_python_wheels',
  'dependency_profile_stored',
  'validating_tool_import',
  'publishing_tool_package',
  'tool_package_published',
] as const

const percentage = computed(() => {
  if (props.status === 'succeeded') return 100
  if (props.status === 'failed') return Math.max(stagePercentage(props.stage), 8)
  if (props.stage === 'dependency_profile_cache_hit') return 76
  if (props.stage === 'dependency_process_output') return 58
  return stagePercentage(props.stage)
})
const progressCounter = computed(() => {
  if (props.status === 'succeeded') return t('toolPreparation.completed')
  if (props.status === 'failed') return t('toolPreparation.stopped')
  const index = orderedStages.indexOf(props.stage as typeof orderedStages[number])
  return `${Math.max(1, index + 1)} / ${orderedStages.length}`
})
const heading = computed(() => ({
  running: t('toolPreparation.running'),
  succeeded: t('toolPreparation.succeeded'),
  failed: t('toolPreparation.failed'),
})[props.status])
const stageLabel = computed(() => t(stageKey(props.stage)))

function stagePercentage(stage: string): number {
  const index = orderedStages.indexOf(stage as typeof orderedStages[number])
  return index < 0 ? 5 : Math.round(((index + 1) / orderedStages.length) * 96)
}

function stageKey(stage: string) {
  const known = new Set<string>([
    ...orderedStages,
    'dependency_profile_cache_hit',
    'dependency_process_output',
  ])
  return `toolPreparation.stage.${known.has(stage) ? stage : 'preparing'}` as Parameters<typeof t>[0]
}
</script>

<style scoped>
.dependency-progress {
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr);
  gap: 14px;
  padding: 14px;
  border: 1px solid var(--app-border);
  border-radius: 18px;
  background: var(--app-surface-muted);
}
.progress-mascot { display: grid; min-height: 72px; place-items: center; border-radius: 13px; background: var(--app-surface); }
.progress-content { display: grid; min-width: 0; align-content: center; gap: 9px; }
.progress-heading { display: flex; align-items: start; justify-content: space-between; gap: 12px; }
.progress-heading > div { display: grid; gap: 2px; }
.progress-heading strong { color: var(--app-text); font-size: 13px; }
.progress-heading span, .progress-heading small { color: var(--app-text-muted); font-size: 10px; }
.requirement-list { display: flex; flex-wrap: wrap; gap: 5px; }
.requirement-list span { padding: 3px 7px; border: 1px solid var(--app-border); border-radius: 999px; color: var(--app-text-secondary); background: var(--app-surface); font-family: ui-monospace, monospace; font-size: 9px; }
.progress-logs { min-width: 0; color: var(--app-text-muted); font-size: 10px; }
.progress-logs summary { cursor: pointer; }
.progress-logs pre { max-height: 126px; margin: 7px 0 0; overflow: auto; padding: 9px; border-radius: 10px; color: var(--app-text-secondary); background: var(--app-surface); font: 9px/1.55 ui-monospace, monospace; white-space: pre-wrap; word-break: break-word; }
.progress-error { margin: 0; color: var(--app-text); font-size: 10px; line-height: 1.55; }
@media (max-width: 600px) { .dependency-progress { grid-template-columns: 1fr; } .progress-mascot { display: none; } }
</style>
