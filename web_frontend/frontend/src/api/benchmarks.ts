import { requestJson, withQuery } from './http'

export type BenchmarkRunStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled' | 'interrupted'

export interface BenchmarkImplementation {
  label: string
  revision: string
  parameters: Record<string, unknown>
}

export interface BenchmarkRunSpec {
  kind: 'performance' | 'operator_analysis'
  name: string
  profile_id: string
  prompt: string
  max_output_tokens: number
  temperature: number
  seed: number
  warmup_iterations: number
  measured_iterations: number
  telemetry_interval_ms: number
  implementation: BenchmarkImplementation
  operator_analysis?: BenchmarkOperatorAnalysisSpec | null
}

export interface BenchmarkOperatorAnalysisSpec {
  prefill_tokens: number
  decode_tokens: number
  repetitions: number
  top_kernels: number
}

export interface BenchmarkTelemetryPoint {
  elapsed_ms: number
  used_memory_bytes?: number | null
  gpu_utilization_percent?: number | null
  memory_activity_percent?: number | null
  power_watts?: number | null
  temperature_celsius?: number | null
}

export interface BenchmarkSample {
  sample_index: number
  warmup: boolean
  status: 'completed' | 'failed'
  started_at: string
  ttft_ms?: number | null
  end_to_end_ms?: number | null
  prompt_tokens?: number | null
  completion_tokens?: number | null
  cache_tokens?: number | null
  prompt_ms?: number | null
  decode_ms?: number | null
  prompt_tokens_per_second?: number | null
  decode_tokens_per_second?: number | null
  peak_vram_bytes?: number | null
  average_gpu_utilization_percent?: number | null
  peak_gpu_utilization_percent?: number | null
  average_power_watts?: number | null
  peak_power_watts?: number | null
  peak_temperature_celsius?: number | null
  output_text: string
  finish_reason: string
  telemetry: BenchmarkTelemetryPoint[]
  error: string
}

export interface BenchmarkMetricStats {
  count: number
  mean: number
  minimum: number
  maximum: number
  p50: number
  p95: number
  standard_deviation: number
}

export interface BenchmarkPromptCacheSummary {
  metric_version: 'legacy' | 'prompt_prefix_reuse.v1'
  prompt_tokens: number
  cached_tokens: number
  processed_tokens: number
  hit_rate_percent: number
}

export interface BenchmarkOperatorKernelStat {
  name: string
  display_name: string
  family: string
  descriptions: Record<string, string>
  variants: string[]
  variant_count: number
  calls: number
  total_duration_ns: number
  average_duration_ns: number
  duration_percent: number
}

export interface BenchmarkOperatorGraphStat {
  operation: string
  backend: string
  count: number
}

export interface BenchmarkCustomKernelStat {
  kernel_id: string
  display_name: string
  family: string
  descriptions: Record<string, string>
  selected_count: number
  dispatch_count: number
  fallback_count: number
  fallback_reasons: Record<string, number>
}

export interface BenchmarkOperatorDispatchVariantStat {
  operation: 'mmvq' | 'mmq'
  weight_type: string
  m: number
  n: number
  k: number
  has_ids: boolean
  has_fusion: boolean
  experts: number
  active_experts: number
  configuration: Record<string, unknown>
  calls: number
  total_duration_ns: number
  average_duration_ns: number
  duration_percent: number
}

export interface BenchmarkOperatorPhaseResult {
  phase: 'prefill' | 'decode'
  elapsed_seconds: number
  benchmark_rows: Array<Record<string, unknown>>
  top_kernels: BenchmarkOperatorKernelStat[]
  graph_operators: BenchmarkOperatorGraphStat[]
  custom_kernels: BenchmarkCustomKernelStat[]
  dispatch_variants: BenchmarkOperatorDispatchVariantStat[]
  artifact_directory: string
  warnings: string[]
}

export interface BenchmarkOperatorAnalysisResult {
  profiler: string
  gpu_graphs_disabled_for_attribution: boolean
  runtime_was_paused: boolean
  runtime_restored: boolean
  phases: BenchmarkOperatorPhaseResult[]
  warnings: string[]
}

export interface BenchmarkSummary {
  measured_samples: number
  successful_samples: number
  ttft_ms?: BenchmarkMetricStats | null
  end_to_end_ms?: BenchmarkMetricStats | null
  prompt_tokens_per_second?: BenchmarkMetricStats | null
  decode_tokens_per_second?: BenchmarkMetricStats | null
  peak_vram_bytes?: BenchmarkMetricStats | null
  average_gpu_utilization_percent?: BenchmarkMetricStats | null
  peak_gpu_utilization_percent?: BenchmarkMetricStats | null
  average_power_watts?: BenchmarkMetricStats | null
  peak_power_watts?: BenchmarkMetricStats | null
  prompt_cache?: BenchmarkPromptCacheSummary | null
}

export interface BenchmarkRun {
  run_id: string
  status: BenchmarkRunStatus
  spec: BenchmarkRunSpec
  progress_completed: number
  progress_total: number
  environment: Record<string, unknown>
  samples: BenchmarkSample[]
  summary?: BenchmarkSummary | null
  operator_analysis?: BenchmarkOperatorAnalysisResult | null
  error: string
  created_at: string
  started_at: string
  completed_at: string
  updated_at: string
}

export const benchmarkApi = {
  list: (limit = 100) =>
    requestJson<{ runs: BenchmarkRun[] }>(withQuery('/api/benchmarks', { limit })),
  get: (runId: string) =>
    requestJson<{ run: BenchmarkRun }>(`/api/benchmarks/${encodeURIComponent(runId)}`),
  start: (spec: BenchmarkRunSpec) =>
    requestJson<{ run: BenchmarkRun }>('/api/benchmarks', {
      method: 'POST',
      body: JSON.stringify(spec),
    }),
  cancel: (runId: string) =>
    requestJson<{ run: BenchmarkRun }>(`/api/benchmarks/${encodeURIComponent(runId)}/cancel`, {
      method: 'POST',
    }),
  delete: (runId: string) =>
    requestJson<{ deleted: boolean }>(`/api/benchmarks/${encodeURIComponent(runId)}`, {
      method: 'DELETE',
    }),
}
