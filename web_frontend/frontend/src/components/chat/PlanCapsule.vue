<template>
  <n-popover
    v-if="plan"
    trigger="click"
    :placement="side === 'left' ? 'right-start' : 'left-start'"
    :show-arrow="false"
    raw
  >
    <template #trigger>
      <button class="plan-capsule" type="button">
        <span class="plan-mark" :class="`status-${plan.status}`" aria-hidden="true">
          <n-icon size="15"><ListOutline /></n-icon>
        </span>
        <span class="plan-copy">
          <span class="plan-meta">
            <strong>{{ t('planCapsule.title') }}</strong>
            <small>{{ completedCount }}/{{ plan.steps.length }}</small>
          </span>
          <span>{{ currentTitle }}</span>
        </span>
        <span class="plan-chevron" aria-hidden="true">⌄</span>
      </button>
    </template>

    <section class="plan-popover">
      <header>
        <span>
          <small>{{ t('planCapsule.title') }}</small>
          <strong>{{ plan.goal }}</strong>
        </span>
        <em>{{ statusLabel }}</em>
      </header>
      <div class="plan-chain">
        <article
          v-for="step in plan.steps"
          :key="step.step_id"
          class="plan-node"
          :class="`status-${step.status}`"
        >
          <span class="node-rail" aria-hidden="true"><i /></span>
          <span class="node-copy">
            <strong>{{ step.title }}</strong>
            <small v-if="step.objective">{{ step.objective }}</small>
            <small v-if="step.result_summary" class="node-result">{{ step.result_summary }}</small>
          </span>
          <em>{{ stepStatus(step.status) }}</em>
        </article>
      </div>
    </section>
  </n-popover>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NIcon, NPopover } from 'naive-ui'
import { ListOutline } from '@/components/icons'
import { useI18n } from '@/composables/useI18n'
import { useRuntimeStore } from '@/stores/runtime'
import type { PlanStepStatus } from '@/types/protocol'

withDefaults(defineProps<{ side?: 'left' | 'right' }>(), { side: 'left' })

const { t } = useI18n()
const runtimeStore = useRuntimeStore()
const plan = computed(() => runtimeStore.currentPlan)
const completedCount = computed(() => plan.value?.steps.filter(step => (
  step.status === 'completed' || step.status === 'skipped'
)).length || 0)
const currentTitle = computed(() => {
  const value = plan.value
  if (!value) return ''
  const current = value.steps.find(step => step.step_id === value.current_step_id)
  if (current) return current.title
  if (value.status === 'completed') return t('planCapsule.completed')
  if (value.status === 'failed') return t('planCapsule.failed')
  return value.goal
})
const statusLabel = computed(() => t(`planCapsule.status.${plan.value?.status || 'active'}` as any))

function stepStatus(status: PlanStepStatus): string {
  return t(`planCapsule.step.${status}` as any)
}
</script>

<style scoped>
.plan-capsule { display:flex; min-width:190px; max-width:300px; height:48px; align-items:center; gap:9px; padding:5px 10px 5px 6px; border:1px solid var(--app-border); border-radius:999px; background:var(--app-surface); color:var(--app-text); box-shadow:0 7px 20px color-mix(in srgb, var(--app-text) 8%, transparent); cursor:pointer; transition:transform .2s cubic-bezier(.16,1,.3,1), border-color .18s ease, box-shadow .2s ease; }
.plan-capsule:hover { transform:translateY(-2px); border-color:var(--app-text); box-shadow:0 11px 26px color-mix(in srgb, var(--app-text) 12%, transparent); }
.plan-mark { display:grid; width:36px; height:36px; flex:0 0 36px; place-items:center; border-radius:50%; background:var(--app-text); color:var(--app-surface); }
.plan-mark.status-completed { opacity:.62; }
.plan-mark.status-failed { background:var(--app-error); }
.plan-copy { display:grid; min-width:0; flex:1; gap:1px; text-align:left; }
.plan-copy > span:last-child { overflow:hidden; color:var(--app-text-muted); font-size:10px; text-overflow:ellipsis; white-space:nowrap; }
.plan-meta { display:flex; align-items:center; justify-content:space-between; gap:8px; }
.plan-meta strong { font-size:11px; }
.plan-meta small { color:var(--app-text-muted); font-size:9px; }
.plan-chevron { color:var(--app-text-muted); font-size:11px; }
.plan-popover { width:min(430px, calc(100vw - 44px)); max-height:min(68vh, 620px); overflow:auto; border:1px solid var(--app-border); border-radius:20px; background:var(--app-surface); box-shadow:0 24px 64px color-mix(in srgb, var(--app-text) 16%, transparent); }
.plan-popover header { display:flex; align-items:flex-start; justify-content:space-between; gap:18px; padding:18px 19px 15px; border-bottom:1px solid var(--app-divider); }
.plan-popover header span { display:grid; min-width:0; gap:4px; }
.plan-popover header small { color:var(--app-text-muted); font-size:9px; font-weight:700; letter-spacing:.12em; text-transform:uppercase; }
.plan-popover header strong { font-size:14px; line-height:1.45; }
.plan-popover em, .plan-node em { flex:0 0 auto; color:var(--app-text-muted); font-size:9px; font-style:normal; }
.plan-chain { padding:15px 18px 18px; }
.plan-node { position:relative; display:grid; grid-template-columns:22px minmax(0,1fr) auto; gap:9px; min-height:54px; }
.node-rail { position:relative; display:flex; justify-content:center; }
.node-rail::after { position:absolute; top:18px; bottom:-2px; width:1px; background:var(--app-divider); content:''; }
.plan-node:last-child .node-rail::after { display:none; }
.node-rail i { position:relative; z-index:1; width:9px; height:9px; margin-top:5px; border:2px solid var(--app-border); border-radius:50%; background:var(--app-surface); }
.status-in_progress .node-rail i { border-color:var(--app-text); box-shadow:0 0 0 4px color-mix(in srgb, var(--app-text) 9%, transparent); }
.status-completed .node-rail i { border-color:var(--app-text); background:var(--app-text); }
.status-failed .node-rail i { border-color:var(--app-error); background:var(--app-error); }
.node-copy { display:grid; align-content:start; gap:3px; padding-bottom:14px; }
.node-copy strong { font-size:12px; line-height:1.4; }
.node-copy small { color:var(--app-text-muted); font-size:10px; line-height:1.45; }
.node-copy .node-result { color:var(--app-text); }
@media (prefers-reduced-motion:reduce) { .plan-capsule { transition:none; } }
</style>
