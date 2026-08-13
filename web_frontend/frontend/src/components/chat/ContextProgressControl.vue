<template>
  <n-popover trigger="hover" placement="top" :show-arrow="false" :delay="80" :duration="160">
    <template #trigger>
      <button
        class="context-progress-trigger"
        :class="{ 'is-compressing': isCompressing, 'is-unknown': usagePercent === null }"
        type="button"
        :aria-label="t('status.context')"
        :title="`${t('status.context')}：${usageText}`"
      >
        <span
          class="context-progress-ring"
          :style="{ '--context-progress': `${usagePercent ?? 0}%` }"
          aria-hidden="true"
        >
          <ComboPngIcon name="context" :size="28" />
          <i
            v-if="thresholdPercent !== null"
            class="ring-threshold"
            :style="{ transform: `rotate(${thresholdAngle}deg)` }"
          />
        </span>
        <span class="ring-label">{{ ringLabel }}</span>
      </button>
    </template>

    <div class="context-progress-bubble" role="status" aria-live="polite">
      <div class="bubble-heading">
        <strong>{{ t('status.context') }}</strong>
        <span>{{ usageText }}</span>
      </div>
      <div class="bubble-meter">
        <span class="bubble-meter-progress" :style="{ width: meterWidth }"></span>
        <span
          v-if="usagePercent !== null"
          class="bubble-progress-runner"
          :style="{ left: `${usageMarkerPercent}%` }"
          aria-hidden="true"
        >
          <ComboFrameAnimation
            character="companion"
            action="running"
            :size="28"
          />
        </span>
        <span
          v-if="thresholdPercent !== null"
          class="bubble-threshold-flag"
          :style="{ left: `${thresholdPercent}%` }"
          aria-hidden="true"
        >
          <ComboPngIcon name="finish-flag" :size="26" />
        </span>
      </div>
      <div class="bubble-meta">
        <span>{{ percentText }}</span>
        <span>{{ thresholdText }}</span>
      </div>
      <div v-if="compressionText" class="compression-copy" :class="runtimeStore.contextActivity.status">
        <i v-if="isCompressing"></i>
        <span>{{ compressionText }}</span>
      </div>
    </div>
  </n-popover>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NPopover } from 'naive-ui'
import ComboFrameAnimation from '@/components/brand/ComboFrameAnimation.vue'
import ComboPngIcon from '@/components/icons/ComboPngIcon.vue'
import { useI18n } from '@/composables/useI18n'
import { useRuntimeStore } from '@/stores/runtime'
import {
  contextWindowPercentLabel,
  contextWindowThresholdLabel,
  contextWindowThresholdPercent,
  contextWindowUsageLabel,
  contextWindowUsagePercent,
  formatCompactTokenCount,
} from '@/utils/contextWindowMeter'

const runtimeStore = useRuntimeStore()
const { t } = useI18n()
const contextWindow = computed(() => runtimeStore.contextWindow)
const usagePercent = computed(() => contextWindow.value ? contextWindowUsagePercent(contextWindow.value) : null)
const thresholdPercent = computed(() => contextWindow.value ? contextWindowThresholdPercent(contextWindow.value) : null)
const meterWidth = computed(() => `${usagePercent.value ?? 0}%`)
const usageMarkerPercent = computed(() => Math.min(100, Math.max(0, usagePercent.value ?? 0)))
const thresholdAngle = computed(() => ((thresholdPercent.value ?? 0) / 100) * 360 - 90)
const ringLabel = computed(() => usagePercent.value === null ? '–' : `${Math.round(usagePercent.value)}`)
const usageText = computed(() => contextWindow.value ? contextWindowUsageLabel(contextWindow.value) : '- / -')
const percentText = computed(() => contextWindow.value
  ? contextWindowPercentLabel(contextWindow.value, {
    unknownUsage: t('status.waitContextEvent'),
    used: t('status.recorded'),
    compressionThreshold: t('status.compressionThreshold', { tokens: '' }).trim(),
  })
  : t('status.waitContextEvent'))
const thresholdText = computed(() => contextWindow.value
  ? contextWindowThresholdLabel(contextWindow.value, {
    unknownUsage: t('status.waitContextEvent'),
    used: t('status.recorded'),
    compressionThreshold: t('status.compressionThreshold', { tokens: '' }).trim(),
  })
  : t('status.compressionThreshold', { tokens: '-' }))
const isCompressing = computed(() => runtimeStore.contextActivity.status === 'running')
const compressionText = computed(() => {
  const activity = runtimeStore.contextActivity
  const payload = activity.payload || {}
  if (activity.status === 'running') {
    return t('status.contextCompressionRunning', {
      before: formatCompactTokenCount(optionalNumber(payload.token_estimate_before)),
    })
  }
  if (activity.status === 'completed') {
    const originalCount = Number(payload.original_message_count || 0)
    const compressedCount = Number(payload.compressed_message_count || 0)
    const compactedCount = optionalNumber(payload.compacted_message_count)
    return t('status.contextCompressionCompleted', {
      before: formatCompactTokenCount(optionalNumber(payload.token_estimate_before)),
      after: formatCompactTokenCount(optionalNumber(payload.token_estimate_after)),
      count: compactedCount ?? Math.max(0, originalCount - compressedCount + 1),
    })
  }
  if (activity.status === 'failed') {
    return t('status.contextCompressionFailed', { reason: String(payload.error || t('common.unknown')) })
  }
  return ''
})

function optionalNumber(value: unknown): number | null {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}
</script>

<style scoped>
.context-progress-trigger {
  position: relative;
  width: 38px;
  height: 38px;
  flex: 0 0 auto;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: var(--app-text);
  cursor: default;
  transition: transform .22s cubic-bezier(.16, 1, .3, 1), background .18s ease;
}
.context-progress-trigger:hover { transform: scale(1.08); background: var(--app-surface-muted); }
.context-progress-ring {
  position: absolute;
  inset: 2px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: conic-gradient(var(--app-text) var(--context-progress), var(--app-divider) 0);
  transition: background .48s cubic-bezier(.16, 1, .3, 1);
}
.context-progress-ring::after {
  position: absolute;
  inset: 2.5px;
  border-radius: inherit;
  background: var(--app-surface);
  content: '';
}
.context-progress-ring :deep(.combo-png-icon) { position: relative; z-index: 1; opacity: 1; }
.ring-threshold {
  position: absolute;
  z-index: 2;
  top: 0;
  left: calc(50% - 1px);
  width: 2px;
  height: 5px;
  border-radius: 2px;
  background: var(--app-warning);
  transform-origin: 1px 17px;
}
.ring-label { position: relative; z-index: 3; padding-top: 1px; font-size: 8px; font-weight: 750; }
.is-compressing .context-progress-ring { animation: context-ring-spin 1.1s linear infinite; }
.context-progress-bubble { width: 280px; padding: 5px 3px; }
.bubble-heading, .bubble-meta { display: flex; justify-content: space-between; gap: 12px; }
.bubble-heading { align-items: baseline; font-size: 12px; }
.bubble-heading span, .bubble-meta { color: var(--app-text-muted); font-size: 10px; }
.bubble-meter { position: relative; height: 5px; margin: 12px 0 8px; overflow: visible; border-radius: 999px; background: var(--app-divider); }
.bubble-meter-progress {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--app-text);
  transition: width .48s cubic-bezier(.16, 1, .3, 1);
}
.bubble-progress-runner {
  position: absolute;
  top: 50%;
  z-index: 3;
  display: grid;
  width: 28px;
  height: 30px;
  place-items: center;
  pointer-events: none;
  transform: translate(-50%, -70%);
  transition: left .48s cubic-bezier(.16, 1, .3, 1);
  filter: drop-shadow(0 1px 1px rgb(0 0 0 / 10%));
}
.bubble-threshold-flag {
  position: absolute;
  top: 50%;
  z-index: 2;
  display: grid;
  width: 26px;
  height: 26px;
  place-items: center;
  pointer-events: none;
  transform: translate(-44%, -72%);
  filter: drop-shadow(0 1px 1px rgb(0 0 0 / 9%));
}
.compression-copy { display: flex; align-items: flex-start; gap: 7px; margin-top: 12px; padding-top: 10px; border-top: 1px solid var(--app-divider); font-size: 11px; line-height: 1.45; }
.compression-copy i { width: 6px; height: 6px; flex: 0 0 auto; margin-top: 5px; border-radius: 50%; background: currentColor; animation: context-dot-pulse 1s ease-in-out infinite; }
.compression-copy.failed { color: var(--app-error); }
.compression-copy.completed { color: var(--app-success); }
@keyframes context-ring-spin { to { transform: rotate(360deg); } }
@keyframes context-dot-pulse { 50% { transform: scale(1.65); opacity: .45; } }
@media (prefers-reduced-motion: reduce) { .context-progress-trigger, .context-progress-ring, .bubble-meter-progress, .bubble-progress-runner, .compression-copy i { animation: none; transition: none; } }
</style>
