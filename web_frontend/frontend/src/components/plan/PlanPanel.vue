<template>
  <div v-if="runtimeStore.currentPlan" class="plan-panel" :class="{ compact }">
    <div class="plan-header">
      <n-text strong>{{ runtimeStore.currentPlan.goal }}</n-text>
      <n-tag :type="planStatusType" size="small">
        {{ runtimeStore.currentPlan.status }}
      </n-tag>
    </div>

    <div class="plan-steps">
      <div
        v-for="step in runtimeStore.currentPlan.steps"
        :key="step.step_id"
        class="plan-step"
        :class="[`status-${step.status}`]"
      >
        <div class="step-header">
          <n-icon :component="stepIcon(step.status)" />
          <span class="step-title">{{ step.title }}</span>
        </div>
        <div v-if="!compact && step.objective" class="step-objective">
          {{ step.objective }}
        </div>
        <div v-if="step.result_summary" class="step-result">
          {{ step.result_summary }}
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NText, NTag, NIcon } from 'naive-ui'
import { CheckmarkCircle, CloseCircle, EllipseOutline, TimeOutline } from '@vicons/ionicons5'
import { useRuntimeStore } from '@/stores/runtime'
import type { PlanStepStatus } from '@/types/protocol'

defineProps<{
  compact?: boolean
}>()

const runtimeStore = useRuntimeStore()

const planStatusType = computed(() => {
  const status = runtimeStore.currentPlan?.status
  if (!status) return 'default'
  if (status.includes('completed')) return 'success'
  if (status.includes('failed')) return 'error'
  if (status.includes('running')) return 'info'
  return 'default'
})

function stepIcon(status: PlanStepStatus) {
  const icons = {
    pending: EllipseOutline,
    in_progress: TimeOutline,
    completed: CheckmarkCircle,
    failed: CloseCircle,
    skipped: EllipseOutline,
  }
  return icons[status] || EllipseOutline
}
</script>

<style scoped>
.plan-panel {
  padding: 16px;
  background: var(--n-color-embedded);
  border-radius: 8px;
}

.plan-panel.compact {
  padding: 12px;
}

.plan-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.plan-steps {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.plan-step {
  padding: 12px;
  background: var(--n-color);
  border-radius: 6px;
  border-left: 3px solid var(--n-border-color);
}

.plan-step.status-in_progress {
  border-left-color: var(--n-info-color);
}

.plan-step.status-completed {
  border-left-color: var(--n-success-color);
  opacity: 0.7;
}

.plan-step.status-failed {
  border-left-color: var(--n-error-color);
}

.step-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
}

.step-objective,
.step-result {
  margin-top: 6px;
  font-size: 13px;
  color: var(--n-text-color-2);
}

.step-result {
  font-style: italic;
}
</style>
