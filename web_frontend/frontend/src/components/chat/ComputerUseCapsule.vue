<template>
  <Teleport to="body">
    <aside v-if="visible && activity.status !== 'idle' && !dismissed" ref="panelRef" class="cu-capsule" :class="{ expanded, dragging }" :style="panelStyle" :aria-label="t('cu.title')">
      <ActivityCapsule :title="title" :subtitle="subtitle" :active="running" :expanded="expanded" @select="toggleExpanded" @pointerdown="beginPanelDrag">
        <template #leading>
          <img v-if="activity.target?.iconDataUrl" class="app-icon" :src="activity.target.iconDataUrl" alt="">
          <span v-else class="status-dot" :class="activity.status" aria-hidden="true" />
        </template>
        <template #actions>
          <span class="capsule-grip" aria-hidden="true">⠿</span>
          <button v-if="running" type="button" :disabled="stopping || !activity.requestId" @click="stop">{{ t(stopping ? 'cu.stopping' : 'cu.stop') }}</button>
          <button type="button" :aria-label="t(expanded ? 'browser.minimize' : 'browser.expand')" @click="expanded = !expanded">{{ expanded ? '⌄' : '⌃' }}</button>
          <button v-if="!running" type="button" :aria-label="t('common.close')" @click="dismissed = true">×</button>
        </template>
      </ActivityCapsule>
      <section v-if="expanded" class="cu-details">
        <header><strong>{{ t('conversation.computerUse.screenshot') }}</strong><span>{{ t('cu.snapshot') }}</span></header>
        <p v-if="activity.screenshot && activity.screenshotError" class="error">{{ t('conversation.computerUse.screenshotUnavailable') }}</p>
        <img v-if="activity.screenshot" class="snapshot" :src="activity.screenshot.dataUrl" :width="activity.screenshot.width" :height="activity.screenshot.height" :alt="title">
        <p v-else>{{ t('conversation.computerUse.screenshotUnavailable') }}</p>
        <ol v-if="operations.length" class="operation-list" :aria-label="t('cu.steps')">
          <li v-for="operation in displayedOperations" :key="operation.id" :class="{ failed: operation.status === 'failed' && !operation.inputVerification, unconfirmed: operation.inputVerification === 'unconfirmed' }">
            <span class="step-number">{{ operation.step }}</span>
            <div class="step-content">
              <div class="step-heading"><strong>{{ operationTitle(operation) }}</strong><span>{{ operationStatus(operation) }}</span></div>
              <p class="step-target">{{ [operation.app, operationTarget(operation)].filter(Boolean).join(' · ') }}</p>
              <p v-if="operation.errorCode" class="step-error">{{ errorMessage(operation.errorCode) }}</p>
            </div>
          </li>
        </ol>
        <p v-else class="empty-steps">{{ t('cu.waitingStep') }}</p>
      </section>
    </aside>
  </Teleport>
</template>
<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useFloatingCapsule } from '@/composables/useFloatingCapsule'
import { isComputerUseToolName } from '@/utils/computerUse'
import type { ComputerUseOperationView } from '@/types/protocol'
import ActivityCapsule from '@/components/common/ActivityCapsule.vue'
import { useRuntimeStore } from '@/stores/runtime'
import { useCommand } from '@/composables/useCommand'
import { useI18n } from '@/composables/useI18n'
const store = useRuntimeStore()
const commands = useCommand()
const { t } = useI18n()
const activity = computed(() => store.computerUseActivity)
const panelRef = ref<HTMLElement | null>(null)
const { panelPosition, panelStyle, dragging, beginPanelDrag, clampPanelPosition, shouldSuppressClick } = useFloatingCapsule(panelRef)
const expanded = ref(true)
const visible = ref(false)
const dismissed = ref(false)
const stopping = ref(false)
const operations = computed(() => activity.value.operations || [])
const displayedOperations = computed(() => [...operations.value].reverse())
const latestOperation = computed(() => operations.value.at(-1))
const running = computed(() => ['running', 'approval'].includes(activity.value.status))
const title = computed(() => latestOperation.value?.app || activity.value.target?.displayName || t('cu.title'))
const subtitle = computed(() => {
  if (stopping.value && running.value) return t('cu.stopping')
  if (!running.value) return t(`cu.${activity.value.status}` as any)
  if (activity.value.phase === 'analyzing') return t('cu.planning')
  return latestOperation.value ? operationTitle(latestOperation.value) : t('cu.waitingStep')
})
watch(() => `${activity.value.requestId || ''}:${activity.value.toolCallId || ''}`, () => {
  visible.value = false
  expanded.value = true
  panelPosition.value = null
  dismissed.value = false
  stopping.value = false
})
// Wait for the ordinary tool-call lifecycle; never open on a proposal/approval alone.
watch(() => {
  const invocation = store.tools.find(tool =>
    isComputerUseToolName(tool.toolName)
    && tool.requestId === activity.value.requestId
    && tool.toolCallId === activity.value.toolCallId)
  return invocation && ['started', 'observed', 'completed'].includes(invocation.status)
    ? `${invocation.requestId}:${invocation.toolCallId}` : null
}, started => {
  if (started) {
    visible.value = true
    void nextTick(clampPanelPosition)
  }
}, { immediate: true, flush: 'post' })
watch(() => [expanded.value, activity.value.screenshot?.dataUrl], () => {
  if (visible.value) void nextTick(clampPanelPosition)
}, { flush: 'post' })
function toggleExpanded() {
  if (!shouldSuppressClick()) expanded.value = !expanded.value
}
watch(running, value => { if (!value) stopping.value = false })
const toolLabels: Record<string, string> = {
  list_apps: 'cu.listApps', get_app_state: 'cu.observe', click: 'cu.click',
  set_input_target: 'cu.bindTarget',
  type_text: 'cu.typeText', set_value: 'cu.setValue', press_key: 'cu.pressKey',
  scroll: 'cu.scroll', drag: 'cu.drag', perform_secondary_action: 'cu.secondary',
}
function operationTitle(operation: ComputerUseOperationView) {
  if (operation.tool === 'perform_secondary_action' && operation.action?.toLowerCase() === 'raise') return t('cu.raise')
  return t((toolLabels[operation.tool] || 'cu.running') as any)
}
function operationTarget(operation: ComputerUseOperationView) {
  if (operation.key) return t('cu.keyTarget', { key: operation.key })
  const target = operation.elementIndex != null ? t('cu.elementTarget', { index: operation.elementIndex })
    : operation.x != null && operation.y != null ? t('cu.coordinateTarget', { x: operation.x, y: operation.y })
    : operation.tool === 'type_text' ? t('cu.focusTarget') : ''
  return [target, operation.textLength != null ? t('cu.textLength', { count: operation.textLength }) : ''].filter(Boolean).join(' · ')
}
function operationStatus(operation: ComputerUseOperationView) {
  if (operation.status === 'running') return running.value ? t('cu.executing') : t('cu.endedUnverified')
  if (operation.inputVerification === 'unconfirmed') return t('cu.inputUnconfirmed')
  if (operation.valueVerified) return t('cu.valueVerified')
  if (operation.status === 'failed') return t('cu.failed')
  return t(['list_apps', 'get_app_state'].includes(operation.tool) ? 'cu.observed' : 'cu.returned')
}
function errorMessage(code: string) {
  const errors: Record<string, string> = {
    'input.target_invalid': 'cu.errorTarget', 'input.focus_mismatch': 'cu.errorFocus',
    'input.receiver_unconfirmed': 'cu.errorFocus',
    'input.delivery_interrupted': 'cu.errorWrite',
    'input.not_writable': 'cu.errorWritable', 'input.unsupported': 'cu.errorUnsupported',
    'input.write_failed': 'cu.errorWrite', 'input.verification_unavailable': 'cu.errorRead',
    'input.readback_mismatch': 'cu.errorMismatch',
    'input.verification_unconfirmed': 'cu.errorUnconfirmed',
    'input.target_required': 'cu.errorTargetRequired',
    'input.target_stale': 'cu.errorSelectionStale',
    'input.selection_unconfirmed': 'cu.errorSelectionStale',
    'input.background_unsupported': 'cu.errorBackground',
    'observation.stale': 'cu.errorObservation', 'observation.required': 'cu.errorObservation',
    'observation.unavailable': 'cu.errorObservation',
    'click.target_invalid': 'cu.errorTarget', 'click.unsupported': 'cu.errorClick',
  }
  return t((errors[code] || 'cu.errorNative') as any)
}
function stop() {
  if (!activity.value.requestId || stopping.value) return
  commands.cancelRequest('user_cancelled', activity.value.requestId)
  stopping.value = true
}
</script>
<style scoped>
.cu-capsule { position: fixed;  z-index: 35; width: min(340px, calc(100vw - 36px)); display: flex; flex-direction: column; gap: 8px; color: var(--app-text); }
.capsule-grip { padding: 6px 4px; cursor: grab; touch-action: none; color: var(--app-text-muted); }
.cu-capsule :deep(.activity-capsule) { cursor: grab; touch-action: none; user-select: none; }
.cu-capsule.dragging :deep(.activity-capsule) { cursor: grabbing; }
.cu-capsule.expanded { width: min(460px, calc(100vw - 36px)); }
.cu-capsule button { border: 0; background: transparent; color: inherit; cursor: pointer; }
.cu-capsule button:disabled { opacity: .5; cursor: default; }
.app-icon { width: 22px; height: 22px; object-fit: contain; }
.status-dot { width: 8px; height: 8px; flex-shrink: 0; border-radius: 50%; background: var(--app-text-muted); }
.status-dot.running, .status-dot.approval { background: var(--app-primary-color); }
.status-dot.failed, .error { color: var(--app-error-color, #c34242); }
.status-dot.failed { background: currentColor; }
.cu-details { max-height: min(65vh, 640px); overflow: auto; padding: 12px; border: 1px solid var(--app-border); border-radius: 18px; background: var(--app-surface); box-shadow: var(--app-shadow-sm); font-size: 12px; }
.cu-details header { display: flex; justify-content: space-between; gap: 8px; margin-bottom: 10px; }
.cu-details header span { color: var(--app-text-muted); }
.snapshot { display: block; width: 100%; height: auto; max-height: 36vh; object-fit: contain; }
.operation-list { list-style: none; margin: 14px 0 0; padding: 0; max-height: 220px; overflow: auto; }
.operation-list li { display: flex; gap: 10px; padding: 10px 0; border-top: 1px solid var(--app-border); }
.step-number { flex: 0 0 22px; height: 22px; display: grid; place-items: center; border-radius: 50%; background: var(--app-surface-hover); color: var(--app-text-muted); font-size: 10px; font-variant-numeric: tabular-nums; }
.step-content { flex: 1; min-width: 0; }
.step-heading { display: flex; justify-content: space-between; align-items: baseline; gap: 10px; }
.step-heading strong { font-size: 12px; font-weight: 600; }
.step-heading span { flex-shrink: 0; color: var(--app-text-muted); font-size: 10px; }
.step-target, .step-error { margin: 4px 0 0; font-size: 11px; line-height: 1.5; overflow-wrap: anywhere; }
.step-target, .empty-steps { color: var(--app-text-muted); }
.failed .step-heading span, .step-error { color: var(--app-error-color, #c34242); }
.unconfirmed .step-heading span, .unconfirmed .step-error { color: var(--app-text-secondary); }
</style>
