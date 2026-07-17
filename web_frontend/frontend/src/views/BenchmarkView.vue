<template>
  <div class="benchmark-view app-scroll-y">
    <header class="context-bar">
      <div class="context-title">
        <div class="title-line">
          <span class="title-icon"><n-icon><BarChartOutline /></n-icon></span>
          <n-text strong class="page-title">{{ t('benchmark.title') }}</n-text>
        </div>
        <n-text depth="3" class="context-subtitle">{{ t('benchmark.subtitle') }}</n-text>
      </div>
      <n-button secondary :loading="loading" @click="refresh()">
        <template #icon><n-icon><Refresh /></n-icon></template>
        {{ t('common.refresh') }}
      </n-button>
    </header>

    <main class="benchmark-content">
      <section class="panel run-form-panel">
        <div class="panel-heading">
          <div>
            <h2>{{ t('benchmark.newRun') }}</h2>
            <p>{{ t('benchmark.implementationHint') }}</p>
          </div>
          <n-tag v-if="activeRun" type="info" :bordered="false">{{ statusLabel(activeRun.status) }}</n-tag>
          <n-tag v-else-if="llamaStatus?.active_build" type="success" :bordered="false">
            {{ llamaStatus.active_build.display_name }}
          </n-tag>
        </div>

        <n-alert v-if="!readyChatProfiles.length" type="warning" :show-icon="true">
          {{ t('benchmark.modelNotReady') }}
        </n-alert>
        <n-alert v-else-if="!llamaStatus?.available" type="warning" :show-icon="true">
          {{ llamaStatus?.error || t('benchmark.implementationUnavailable') }}
        </n-alert>

        <div class="form-grid">
          <label class="field field-wide">
            <span>{{ t('benchmark.runName') }}</span>
            <n-input v-model:value="form.name" :disabled="Boolean(activeRun)" />
          </label>
          <label class="field field-wide">
            <span>{{ t('benchmark.profile') }}</span>
            <n-select
              class="profile-select"
              v-model:value="form.profile_id"
              :options="profileOptions"
              :disabled="Boolean(activeRun)"
            />
          </label>
          <label class="field field-full">
            <span>{{ t('benchmark.prompt') }}</span>
            <n-input
              v-model:value="form.prompt"
              type="textarea"
              :autosize="{ minRows: 4, maxRows: 10 }"
              :placeholder="t('benchmark.promptPlaceholder')"
              :disabled="Boolean(activeRun)"
            />
          </label>
          <label class="field">
            <span>{{ t('benchmark.maxOutputTokens') }}</span>
            <n-input-number v-model:value="form.max_output_tokens" :min="1" :max="32768" :disabled="Boolean(activeRun)" />
          </label>
          <label class="field">
            <span>{{ t('benchmark.temperature') }}</span>
            <n-input-number v-model:value="form.temperature" :min="0" :max="2" :step="0.1" :disabled="Boolean(activeRun)" />
          </label>
          <label class="field">
            <span>{{ t('benchmark.seed') }}</span>
            <n-input-number v-model:value="form.seed" :min="0" :disabled="Boolean(activeRun)" />
          </label>
          <label class="field">
            <span>{{ t('benchmark.warmupIterations') }}</span>
            <n-input-number v-model:value="form.warmup_iterations" :min="0" :max="10" :disabled="Boolean(activeRun)" />
          </label>
          <label class="field">
            <span>{{ t('benchmark.measuredIterations') }}</span>
            <n-input-number v-model:value="form.measured_iterations" :min="1" :max="50" :disabled="Boolean(activeRun)" />
          </label>
          <label class="field">
            <span>{{ t('benchmark.telemetryInterval') }}</span>
            <n-select
              v-model:value="form.telemetry_interval_ms"
              :options="telemetryIntervalOptions"
              :disabled="Boolean(activeRun)"
            />
          </label>
        </div>

        <div class="form-actions">
          <n-button
            v-if="!activeRun"
            type="primary"
            :loading="submitting"
            :disabled="!canStart"
            @click="startRun"
          >
            <template #icon><n-icon><Play /></n-icon></template>
            {{ t('benchmark.start') }}
          </n-button>
          <n-button v-else type="error" secondary :loading="submitting" @click="cancelRun(activeRun)">
            <template #icon><n-icon><Stop /></n-icon></template>
            {{ t('benchmark.cancel') }}
          </n-button>
        </div>
      </section>

      <section v-if="selectedRun" class="panel current-run-panel">
        <div class="panel-heading run-heading">
          <div>
            <div class="run-title-line">
              <h2>{{ selectedRun.spec.name }}</h2>
              <n-tag :type="statusTagType(selectedRun.status)" :bordered="false">
                {{ statusLabel(selectedRun.status) }}
              </n-tag>
            </div>
            <p>{{ selectedRun.spec.implementation.label || selectedRun.spec.profile_id }}</p>
          </div>
          <span class="run-time">{{ formatDate(selectedRun.created_at) }}</span>
        </div>

        <div v-if="isActive(selectedRun)" class="run-progress">
          <div class="progress-copy">
            <span>{{ t('benchmark.currentRun') }}</span>
            <strong>{{ t('benchmark.progress', { completed: selectedRun.progress_completed, total: selectedRun.progress_total }) }}</strong>
          </div>
          <n-progress
            type="line"
            status="info"
            processing
            :percentage="runProgress(selectedRun)"
          />
        </div>

        <n-alert v-if="selectedRun.error" type="error" :show-icon="true" class="run-error">
          {{ selectedRun.error }}
        </n-alert>

        <template v-if="selectedRun.summary">
          <div class="section-heading">
            <h3>{{ t('benchmark.summary') }}</h3>
            <span>{{ t('benchmark.measuredSamples', { successful: selectedRun.summary.successful_samples, total: selectedRun.summary.measured_samples }) }}</span>
          </div>
          <div class="metric-grid">
            <article v-for="metric in primaryMetrics" :key="metric.key" class="metric-card">
              <span class="metric-label">{{ metric.label }}</span>
              <strong class="metric-value">{{ formatMetric(metric.key, metricStats(selectedRun, metric.key)?.mean) }}</strong>
              <div class="metric-detail">
                <span>{{ t('benchmark.metricP50') }} {{ formatMetric(metric.key, metricStats(selectedRun, metric.key)?.p50) }}</span>
                <span>{{ t('benchmark.metricP95') }} {{ formatMetric(metric.key, metricStats(selectedRun, metric.key)?.p95) }}</span>
              </div>
            </article>
          </div>

          <template v-if="selectedRun.summary.prompt_cache">
            <div class="section-heading cache-heading">
              <h3>{{ t('benchmark.promptCache') }}</h3>
              <span>{{ t('benchmark.weightedHitRateHint') }}</span>
            </div>
            <div class="metric-grid cache-metric-grid">
              <article class="metric-card">
                <span class="metric-label">{{ t('benchmark.cacheHitRate') }}</span>
                <strong class="metric-value">{{ formatPercent(selectedRun.summary.prompt_cache.hit_rate_percent) }}</strong>
              </article>
              <article class="metric-card">
                <span class="metric-label">{{ t('benchmark.cachedTokens') }}</span>
                <strong class="metric-value">{{ formatTokenCount(selectedRun.summary.prompt_cache.cached_tokens) }}</strong>
              </article>
              <article class="metric-card">
                <span class="metric-label">{{ t('benchmark.processedPromptTokens') }}</span>
                <strong class="metric-value">{{ formatTokenCount(selectedRun.summary.prompt_cache.processed_tokens) }}</strong>
              </article>
              <article class="metric-card">
                <span class="metric-label">{{ t('benchmark.promptTokens') }}</span>
                <strong class="metric-value">{{ formatTokenCount(selectedRun.summary.prompt_cache.prompt_tokens) }}</strong>
              </article>
            </div>
          </template>

          <div class="comparison-heading">
            <div class="section-heading">
              <h3>{{ t('benchmark.comparison') }}</h3>
            </div>
            <n-select
              v-model:value="baselineRunId"
              clearable
              :placeholder="t('benchmark.noBaseline')"
              :options="baselineOptions"
            />
          </div>
          <div v-if="baselineRun" class="comparison-table">
            <div class="comparison-row comparison-header">
              <span>{{ t('benchmark.summary') }}</span>
              <span>{{ selectedRun.spec.name }}</span>
              <span>{{ baselineRun.spec.name }}</span>
              <span>{{ t('benchmark.delta') }}</span>
            </div>
            <div v-for="metric in primaryMetrics" :key="metric.key" class="comparison-row">
              <span>{{ metric.label }}</span>
              <strong>{{ formatMetric(metric.key, metricMean(selectedRun, metric.key)) }}</strong>
              <span>{{ formatMetric(metric.key, metricMean(baselineRun, metric.key)) }}</span>
              <span :class="deltaClass(metric, selectedRun, baselineRun)">
                {{ formatDelta(metric, selectedRun, baselineRun) }}
              </span>
            </div>
            <div
              v-if="selectedRun.summary?.prompt_cache && baselineRun.summary?.prompt_cache"
              class="comparison-row"
            >
              <span>{{ t('benchmark.cacheHitRate') }}</span>
              <strong>{{ formatPercent(selectedRun.summary.prompt_cache.hit_rate_percent) }}</strong>
              <span>{{ formatPercent(baselineRun.summary.prompt_cache.hit_rate_percent) }}</span>
              <span :class="cacheDeltaClass(selectedRun, baselineRun)">
                {{ formatCacheDelta(selectedRun, baselineRun) }}
              </span>
            </div>
          </div>
        </template>

        <div v-if="selectedRun.samples.length" class="samples-section">
          <div class="section-heading"><h3>{{ t('benchmark.samples') }}</h3></div>
          <div class="sample-table-wrap">
            <table class="sample-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>{{ t('common.status') }}</th>
                  <th>{{ t('benchmark.ttft') }}</th>
                  <th>{{ t('benchmark.promptTps') }}</th>
                  <th>{{ t('benchmark.decodeTps') }}</th>
                  <th>{{ t('benchmark.endToEnd') }}</th>
                  <th>{{ t('benchmark.cachedTokens') }}</th>
                  <th>{{ t('benchmark.processedPromptTokens') }}</th>
                  <th>{{ t('benchmark.cacheHitRate') }}</th>
                  <th>{{ t('benchmark.peakVram') }}</th>
                  <th>{{ t('benchmark.peakGpu') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="sample in selectedRun.samples" :key="sample.sample_index">
                  <td>{{ sample.sample_index + 1 }}</td>
                  <td>
                    <n-tag size="small" :bordered="false" :type="sample.status === 'completed' ? 'success' : 'error'">
                      {{ sample.warmup ? t('benchmark.warmup') : t('benchmark.measured') }}
                    </n-tag>
                  </td>
                  <td>{{ formatMetric('ttft_ms', sample.ttft_ms) }}</td>
                  <td>{{ formatMetric('prompt_tokens_per_second', sample.prompt_tokens_per_second) }}</td>
                  <td>{{ formatMetric('decode_tokens_per_second', sample.decode_tokens_per_second) }}</td>
                  <td>{{ formatMetric('end_to_end_ms', sample.end_to_end_ms) }}</td>
                  <td>{{ formatTokenCount(sample.cache_tokens) }}</td>
                  <td>{{ formatTokenCount(sampleProcessedPromptTokens(sample)) }}</td>
                  <td>{{ formatPercent(sampleCacheHitRate(sample)) }}</td>
                  <td>{{ formatMetric('peak_vram_bytes', sample.peak_vram_bytes) }}</td>
                  <td>{{ formatMetric('peak_gpu_utilization_percent', sample.peak_gpu_utilization_percent) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <n-collapse v-if="Object.keys(selectedRun.environment).length" class="environment-collapse">
          <n-collapse-item :title="t('benchmark.environment')" name="environment">
            <pre>{{ formatEnvironment(selectedRun.environment) }}</pre>
          </n-collapse-item>
        </n-collapse>
      </section>

      <section class="panel history-panel">
        <div class="section-heading"><h3>{{ t('benchmark.history') }}</h3></div>
        <n-empty v-if="!runs.length" :description="t('benchmark.noHistory')" />
        <div v-else class="history-list">
          <div
            v-for="run in runs"
            :key="run.run_id"
            class="history-item"
            :class="{ 'is-selected': run.run_id === selectedRun?.run_id }"
            role="button"
            tabindex="0"
            @click="selectedRunId = run.run_id"
            @keydown.enter="selectedRunId = run.run_id"
          >
            <span class="history-main">
              <strong>{{ run.spec.name }}</strong>
              <small>{{ run.spec.implementation.label || run.spec.profile_id }}</small>
            </span>
            <span class="history-metrics">
              <span>{{ formatMetric('ttft_ms', metricMean(run, 'ttft_ms')) }}</span>
              <span>{{ formatMetric('decode_tokens_per_second', metricMean(run, 'decode_tokens_per_second')) }}</span>
            </span>
            <n-tag size="small" :bordered="false" :type="statusTagType(run.status)">{{ statusLabel(run.status) }}</n-tag>
            <span class="history-date">{{ formatDate(run.created_at) }}</span>
            <n-popconfirm
              v-if="!isActive(run)"
              :positive-text="t('common.delete')"
              :negative-text="t('common.cancel')"
              @positive-click="deleteRun(run)"
            >
              <template #trigger>
                <n-button quaternary circle size="small" :title="t('benchmark.deleteRun')" @click.stop>
                  <template #icon><n-icon><TrashOutline /></n-icon></template>
                </n-button>
              </template>
              {{ t('benchmark.deleteRun') }}?
            </n-popconfirm>
          </div>
        </div>
      </section>
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import {
  NAlert,
  NButton,
  NCollapse,
  NCollapseItem,
  NEmpty,
  NIcon,
  NInput,
  NInputNumber,
  NPopconfirm,
  NProgress,
  NSelect,
  NTag,
  NText,
  useMessage,
} from 'naive-ui'
import { BarChartOutline, Play, Refresh, Stop, TrashOutline } from '@/components/icons'
import { useI18n } from '@/composables/useI18n'
import { benchmarkApi } from '@/api/benchmarks'
import type {
  BenchmarkMetricStats,
  BenchmarkRun,
  BenchmarkRunSpec,
  BenchmarkRunStatus,
  BenchmarkSample,
} from '@/api/benchmarks'
import { modelPoolApi } from '@/api/modelPool'
import type { LlamaImplementationStatus, LocalModelProfile, LocalModelRuntime } from '@/api/modelPool'

type MetricKey =
  | 'ttft_ms'
  | 'prompt_tokens_per_second'
  | 'decode_tokens_per_second'
  | 'end_to_end_ms'
  | 'peak_vram_bytes'
  | 'average_gpu_utilization_percent'
  | 'peak_gpu_utilization_percent'
  | 'average_power_watts'
  | 'peak_power_watts'

interface MetricDefinition {
  key: MetricKey
  label: string
  higherIsBetter: boolean
}

const { t } = useI18n()
const message = useMessage()
const loading = ref(false)
const submitting = ref(false)
const runs = ref<BenchmarkRun[]>([])
const profiles = ref<LocalModelProfile[]>([])
const runtimes = ref<LocalModelRuntime[]>([])
const llamaStatus = ref<LlamaImplementationStatus | null>(null)
const selectedRunId = ref<string | null>(null)
const baselineRunId = ref<string | null>(null)
let pollTimer: number | undefined
let pollInProgress = false

const form = reactive<BenchmarkRunSpec>({
  name: '',
  profile_id: '',
  prompt: '',
  max_output_tokens: 256,
  temperature: 0,
  seed: 42,
  warmup_iterations: 1,
  measured_iterations: 3,
  telemetry_interval_ms: 250,
  implementation: { label: '', revision: '', parameters: {} },
})

const readyProfileIds = computed(() => new Set(
  runtimes.value.filter((runtime) => runtime.phase === 'ready').map((runtime) => runtime.profile_id),
))
const readyChatProfiles = computed(() => profiles.value.filter((profile) =>
  profile.kind === 'chat' && profile.enabled && readyProfileIds.value.has(profile.profile_id),
))
const profileOptions = computed(() => readyChatProfiles.value.map((profile) => ({
  label: profileOptionLabel(profile),
  value: profile.profile_id,
})))

function profileOptionLabel(profile: LocalModelProfile): string {
  const displayName = profile.display_name.trim()
  const servedModelName = profile.served_model_name.trim()
  return displayName || servedModelName || profile.profile_id
}
const telemetryIntervalOptions = [100, 250, 500, 1000].map((value) => ({
  label: t('benchmark.milliseconds', { value }),
  value,
}))
const activeRun = computed(() => runs.value.find((run) => isActive(run)) || null)
const selectedRun = computed(() =>
  runs.value.find((run) => run.run_id === selectedRunId.value) || runs.value[0] || null,
)
const baselineRun = computed(() =>
  runs.value.find((run) => run.run_id === baselineRunId.value && run.status === 'completed') || null,
)
const baselineOptions = computed(() => runs.value
  .filter((run) => run.status === 'completed' && run.run_id !== selectedRun.value?.run_id)
  .map((run) => ({ label: `${run.spec.name} · ${formatDate(run.created_at)}`, value: run.run_id })))
const canStart = computed(() => Boolean(
  form.name.trim()
  && form.profile_id
  && form.prompt.trim()
  && readyProfileIds.value.has(form.profile_id)
  && llamaStatus.value?.available,
))
const primaryMetrics = computed<MetricDefinition[]>(() => [
  { key: 'ttft_ms', label: t('benchmark.ttft'), higherIsBetter: false },
  { key: 'prompt_tokens_per_second', label: t('benchmark.promptTps'), higherIsBetter: true },
  { key: 'decode_tokens_per_second', label: t('benchmark.decodeTps'), higherIsBetter: true },
  { key: 'end_to_end_ms', label: t('benchmark.endToEnd'), higherIsBetter: false },
  { key: 'peak_vram_bytes', label: t('benchmark.peakVram'), higherIsBetter: false },
  { key: 'average_gpu_utilization_percent', label: t('benchmark.averageGpu'), higherIsBetter: true },
])

async function refresh(showLoading = true) {
  if (showLoading) loading.value = true
  try {
    const [runResult, profileResult, runtimeResult, llamaResult] = await Promise.all([
      benchmarkApi.list(),
      modelPoolApi.profiles(),
      modelPoolApi.runtimes(),
      modelPoolApi.llamaRuntime(),
    ])
    runs.value = runResult.runs
    profiles.value = profileResult.profiles
    runtimes.value = runtimeResult.runtimes
    llamaStatus.value = llamaResult
    if (!selectedRunId.value && runs.value.length) selectedRunId.value = runs.value[0].run_id
    if (!form.profile_id && readyChatProfiles.value.length) form.profile_id = readyChatProfiles.value[0].profile_id
  } catch (error) {
    if (showLoading) message.error(errorMessage(error))
  } finally {
    if (showLoading) loading.value = false
  }
}

async function startRun() {
  if (!canStart.value) return
  submitting.value = true
  try {
    const result = await benchmarkApi.start({
      ...form,
      name: form.name.trim(),
      prompt: form.prompt.trim(),
      implementation: {
        ...form.implementation,
        label: form.implementation.label.trim(),
        revision: form.implementation.revision.trim(),
      },
    })
    selectedRunId.value = result.run.run_id
    await refresh(false)
  } catch (error) {
    message.error(errorMessage(error))
  } finally {
    submitting.value = false
  }
}

async function cancelRun(run: BenchmarkRun) {
  submitting.value = true
  try {
    await benchmarkApi.cancel(run.run_id)
    await refresh(false)
  } catch (error) {
    message.error(errorMessage(error))
  } finally {
    submitting.value = false
  }
}

async function deleteRun(run: BenchmarkRun) {
  try {
    await benchmarkApi.delete(run.run_id)
    if (selectedRunId.value === run.run_id) selectedRunId.value = null
    if (baselineRunId.value === run.run_id) baselineRunId.value = null
    await refresh(false)
  } catch (error) {
    message.error(errorMessage(error))
  }
}

function isActive(run: BenchmarkRun) {
  return run.status === 'queued' || run.status === 'running'
}

function runProgress(run: BenchmarkRun) {
  if (!run.progress_total) return 0
  return Math.min(100, Math.round((run.progress_completed / run.progress_total) * 100))
}

function metricStats(run: BenchmarkRun, key: MetricKey): BenchmarkMetricStats | null {
  return run.summary?.[key] || null
}

function metricMean(run: BenchmarkRun, key: MetricKey) {
  return metricStats(run, key)?.mean ?? null
}

function formatMetric(key: MetricKey, value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  if (key.endsWith('_ms')) return `${value.toFixed(1)} ms`
  if (key === 'peak_vram_bytes') return formatBytes(value)
  if (key.includes('utilization_percent')) return `${value.toFixed(1)}%`
  if (key.includes('power_watts')) return `${value.toFixed(1)} W`
  return `${value.toFixed(2)} tok/s`
}

function formatBytes(value: number) {
  const gib = value / 1024 ** 3
  return `${gib.toFixed(gib >= 10 ? 1 : 2)} GiB`
}

function formatTokenCount(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return Math.round(value).toLocaleString()
}

function formatPercent(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return `${value.toFixed(1)}%`
}

function sampleProcessedPromptTokens(sample: BenchmarkSample) {
  if (sample.prompt_tokens === null || sample.prompt_tokens === undefined) return null
  if (sample.cache_tokens === null || sample.cache_tokens === undefined) return null
  return Math.max(0, sample.prompt_tokens - sample.cache_tokens)
}

function sampleCacheHitRate(sample: BenchmarkSample) {
  if (!sample.prompt_tokens || sample.cache_tokens === null || sample.cache_tokens === undefined) return null
  return Math.min(100, Math.max(0, sample.cache_tokens / sample.prompt_tokens * 100))
}

function metricDelta(metric: MetricDefinition, current: BenchmarkRun, baseline: BenchmarkRun) {
  const currentValue = metricMean(current, metric.key)
  const baselineValue = metricMean(baseline, metric.key)
  if (currentValue === null || baselineValue === null || baselineValue === 0) return null
  const raw = ((currentValue - baselineValue) / baselineValue) * 100
  return metric.higherIsBetter ? raw : -raw
}

function formatDelta(metric: MetricDefinition, current: BenchmarkRun, baseline: BenchmarkRun) {
  const delta = metricDelta(metric, current, baseline)
  if (delta === null) return '—'
  return `${delta >= 0 ? '+' : ''}${delta.toFixed(1)}%`
}

function deltaClass(metric: MetricDefinition, current: BenchmarkRun, baseline: BenchmarkRun) {
  const delta = metricDelta(metric, current, baseline)
  if (delta === null || Math.abs(delta) < 0.05) return 'delta-neutral'
  return delta > 0 ? 'delta-positive' : 'delta-negative'
}

function cacheHitRate(run: BenchmarkRun) {
  return run.summary?.prompt_cache?.hit_rate_percent ?? null
}

function formatCacheDelta(current: BenchmarkRun, baseline: BenchmarkRun) {
  const currentValue = cacheHitRate(current)
  const baselineValue = cacheHitRate(baseline)
  if (currentValue === null || baselineValue === null) return '—'
  const delta = currentValue - baselineValue
  return `${delta >= 0 ? '+' : ''}${delta.toFixed(1)} pp`
}

function cacheDeltaClass(current: BenchmarkRun, baseline: BenchmarkRun) {
  const currentValue = cacheHitRate(current)
  const baselineValue = cacheHitRate(baseline)
  if (currentValue === null || baselineValue === null) return 'delta-neutral'
  const delta = currentValue - baselineValue
  if (Math.abs(delta) < 0.05) return 'delta-neutral'
  return delta > 0 ? 'delta-positive' : 'delta-negative'
}

function statusLabel(status: BenchmarkRunStatus) {
  const labels: Record<BenchmarkRunStatus, string> = {
    queued: t('connection.connecting'),
    running: t('run.running'),
    completed: t('run.completed'),
    failed: t('run.failed'),
    cancelled: t('run.cancelled'),
    interrupted: t('run.interrupted'),
  }
  return labels[status]
}

function statusTagType(status: BenchmarkRunStatus): 'default' | 'info' | 'success' | 'warning' | 'error' {
  if (status === 'completed') return 'success'
  if (status === 'running' || status === 'queued') return 'info'
  if (status === 'interrupted' || status === 'cancelled') return 'warning'
  if (status === 'failed') return 'error'
  return 'default'
}

function formatDate(value: string) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

function formatEnvironment(environment: Record<string, unknown>) {
  return JSON.stringify(environment, null, 2)
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error)
}

onMounted(async () => {
  await refresh()
  pollTimer = window.setInterval(async () => {
    if (!activeRun.value || pollInProgress) return
    pollInProgress = true
    try {
      await refresh(false)
    } finally {
      pollInProgress = false
    }
  }, 1000)
})

onUnmounted(() => {
  if (pollTimer !== undefined) window.clearInterval(pollTimer)
})
</script>

<style scoped>
.benchmark-view {
  container-name: benchmark;
  container-type: inline-size;
  width: 100%;
  min-width: 0;
  height: 100%;
  background: var(--app-background);
}

.context-bar {
  min-height: 78px;
  padding: var(--app-space-lg) var(--app-space-xl);
  background: var(--app-surface);
  border-bottom: 1px solid var(--app-divider);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-lg);
}

.title-line,
.run-title-line {
  display: flex;
  align-items: center;
  gap: var(--app-space-sm);
}

.title-icon {
  width: 34px;
  height: 34px;
  border-radius: var(--app-radius-md);
  color: var(--app-primary);
  background: var(--app-primary-soft);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
}

.page-title { font-size: 20px; }
.context-title { min-width: 0; }
.context-subtitle { display: block; margin-top: 4px; white-space: normal; line-height: var(--app-leading-normal); }

.benchmark-content {
  width: min(1480px, 100%);
  margin: 0 auto;
  padding: var(--app-space-xl);
  display: grid;
  gap: var(--app-space-lg);
}

.panel {
  background: var(--app-surface);
  border: 1px solid var(--app-divider);
  border-radius: var(--app-radius-lg);
  padding: var(--app-space-xl);
}

.panel-heading,
.section-heading,
.comparison-heading,
.progress-copy {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-lg);
}

.panel-heading { margin-bottom: var(--app-space-lg); }
.panel-heading h2,
.section-heading h3 { margin: 0; color: var(--app-text-strong); }
.panel-heading p { margin: 5px 0 0; color: var(--app-text-muted); }
.section-heading { margin: var(--app-space-xl) 0 var(--app-space-md); }
.section-heading span,
.run-time { color: var(--app-text-muted); font-size: 12px; }

.form-grid {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: var(--app-space-md);
  margin-top: var(--app-space-lg);
}

.field { grid-column: span 1; display: grid; gap: 7px; min-width: 0; }
.field-wide { grid-column: span 3; }
.field-full { grid-column: 1 / -1; }
.field > span { color: var(--app-text); font-size: 12px; font-weight: 600; }
.profile-select { width: 100%; min-width: 0; max-width: 100%; }
.profile-select :deep(.n-base-selection),
.profile-select :deep(.n-base-selection-label),
.profile-select :deep(.n-base-selection-input),
.profile-select :deep(.n-base-selection-input__content) {
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
}
.profile-select :deep(.n-base-selection-input__content) {
  text-overflow: ellipsis;
  white-space: nowrap;
}
.form-actions { margin-top: var(--app-space-lg); display: flex; justify-content: flex-end; }

.run-progress {
  padding: var(--app-space-md);
  border-radius: var(--app-radius-md);
  background: var(--app-surface-muted);
}
.progress-copy { margin-bottom: 8px; }
.run-error { margin-top: var(--app-space-md); }

.metric-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--app-space-md);
}
.cache-metric-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }

.metric-card {
  min-width: 0;
  padding: var(--app-space-lg);
  border: 1px solid var(--app-divider);
  border-radius: var(--app-radius-md);
  background: var(--app-surface-muted);
}
.metric-label { color: var(--app-text-muted); font-size: 12px; }
.metric-value { display: block; margin-top: 8px; font-size: 24px; color: var(--app-text-strong); }
.metric-detail { margin-top: 10px; display: flex; flex-wrap: wrap; gap: var(--app-space-xs) var(--app-space-md); color: var(--app-text-muted); font-size: 11px; }

.comparison-heading { margin-top: var(--app-space-lg); align-items: end; }
.comparison-heading .n-select { width: min(420px, 50%); }
.comparison-table { border: 1px solid var(--app-divider); border-radius: var(--app-radius-md); overflow-x: auto; }
.comparison-row {
  display: grid;
  grid-template-columns: 1.3fr repeat(3, 1fr);
  gap: var(--app-space-md);
  padding: 11px var(--app-space-md);
  border-top: 1px solid var(--app-divider);
  align-items: center;
}
.comparison-row:first-child { border-top: 0; }
.comparison-header { background: var(--app-surface-muted); color: var(--app-text-muted); font-size: 12px; }
.delta-positive { color: var(--app-success); font-weight: 700; }
.delta-negative { color: var(--app-error); font-weight: 700; }
.delta-neutral { color: var(--app-text-muted); }

.sample-table-wrap { overflow-x: auto; border: 1px solid var(--app-divider); border-radius: var(--app-radius-md); }
.sample-table { width: 100%; border-collapse: collapse; white-space: nowrap; }
.sample-table th,
.sample-table td { padding: 10px 12px; text-align: left; border-bottom: 1px solid var(--app-divider); }
.sample-table th { background: var(--app-surface-muted); color: var(--app-text-muted); font-size: 12px; }
.sample-table tr:last-child td { border-bottom: 0; }

.environment-collapse { margin-top: var(--app-space-lg); }
.environment-collapse pre {
  max-height: 420px;
  overflow: auto;
  margin: 0;
  padding: var(--app-space-md);
  border-radius: var(--app-radius-md);
  background: var(--app-surface-muted);
  color: var(--app-text);
  font-size: 12px;
}

.history-list { display: grid; gap: 8px; }
.history-item {
  width: 100%;
  display: grid;
  grid-template-columns: minmax(240px, 1fr) minmax(180px, auto) auto auto auto;
  align-items: center;
  gap: var(--app-space-md);
  padding: 12px;
  border: 1px solid var(--app-divider);
  border-radius: var(--app-radius-md);
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
}
.history-item:hover,
.history-item.is-selected { background: var(--app-surface-muted); border-color: var(--app-primary); }
.history-main { display: grid; gap: 3px; min-width: 0; }
.history-main strong,
.history-main small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.history-main small,
.history-date { color: var(--app-text-muted); }
.history-metrics { display: flex; gap: var(--app-space-md); font-variant-numeric: tabular-nums; }

@container benchmark (max-width: 1100px) {
  .form-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .field, .field-wide { grid-column: span 1; }
  .field-full { grid-column: 1 / -1; }
  .metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .history-item { grid-template-columns: minmax(0, 1fr) auto auto; }
  .history-main { grid-column: 1; }
  .history-metrics { grid-column: 1 / -1; grid-row: 2; flex-wrap: wrap; }
  .history-date { grid-column: 1 / -1; grid-row: 3; font-size: var(--app-font-xs); }
}

@container benchmark (max-width: 700px) {
  .context-bar { align-items: flex-start; flex-wrap: wrap; padding: var(--app-space-md); }
  .context-bar > .n-button { margin-left: 42px; }
  .benchmark-content { padding: var(--app-space-md); }
  .panel { padding: var(--app-space-md); }
  .panel-heading,
  .section-heading,
  .progress-copy { align-items: flex-start; flex-wrap: wrap; }
  .form-grid, .metric-grid { grid-template-columns: 1fr; }
  .field, .field-wide, .field-full { grid-column: 1; }
  .comparison-heading { align-items: stretch; flex-direction: column; }
  .comparison-heading .n-select { width: 100%; }
  .comparison-row { min-width: 620px; grid-template-columns: 1.2fr repeat(3, 1fr); font-size: 12px; }
  .sample-table th,
  .sample-table td { padding: 8px 10px; }
  .history-item { grid-template-columns: minmax(0, 1fr) auto; gap: var(--app-space-sm); }
  .history-main { grid-column: 1 / -1; }
  .history-metrics { grid-column: 1 / -1; }
  .history-date { grid-column: 1 / -1; }
}

@container benchmark (max-width: 420px) {
  .context-bar > .n-button { width: 100%; margin-left: 0; }
  .benchmark-content { padding: var(--app-space-sm); }
  .panel { padding: var(--app-space-sm); }
  .metric-value { font-size: 20px; overflow-wrap: anywhere; }
  .form-actions > .n-button { width: 100%; }
}
</style>
