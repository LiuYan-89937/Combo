import type { ToolExecutionMessagePart } from '@/types/protocol'
import { isRuntimeCancellation } from '@/utils/runtimeCancellation'

// Mirrors the single-tool card: write tools fall back to the requested target
// when the structured result payload is absent or still in flight.
const WRITE_TOOL_NAMES = new Set([
  'edit',
  'write',
  'write_once',
  'multi_edit',
  'apply_patch',
  'str_replace_editor',
  'notebook_edit',
])

const RUNNING_STATUSES = new Set(['requested', 'running', 'streaming', 'awaiting_approval'])

export interface ToolTraceSummary {
  count: number
  failureCount: number
  runningCount: number
  changedFileCount: number
  durationMs: number | null
}

/**
 * Aggregates one tool trajectory group into the single caption line shown while
 * the group is collapsed. Everything is derived from parts already in the
 * transcript, so no extra runtime event is required.
 */
export function toolTraceSummary(executions: readonly ToolExecutionMessagePart[]): ToolTraceSummary {
  const changedFiles = new Set<string>()
  let failureCount = 0
  let runningCount = 0
  let earliestStart = Number.POSITIVE_INFINITY
  let latestCompletion = Number.NEGATIVE_INFINITY
  let stillRunning = false

  executions.forEach((execution) => {
    if (isToolExecutionCancelled(execution)) return
    if (isToolExecutionFailed(execution)) failureCount += 1
    if (isToolExecutionRunning(execution)) {
      runningCount += 1
      stillRunning = true
    }
    changedFilePaths(execution).forEach(path => changedFiles.add(path))

    const startedAt = Date.parse(String(execution.startedAt || ''))
    if (Number.isFinite(startedAt)) earliestStart = Math.min(earliestStart, startedAt)
    const completedAt = Date.parse(String(execution.completedAt || ''))
    if (Number.isFinite(completedAt)) latestCompletion = Math.max(latestCompletion, completedAt)
  })

  return {
    count: executions.length,
    failureCount,
    runningCount,
    changedFileCount: changedFiles.size,
    durationMs: traceDurationMs(earliestStart, latestCompletion, stillRunning),
  }
}

export function isToolExecutionCancelled(execution: ToolExecutionMessagePart): boolean {
  return execution.status === 'cancelled' || isRuntimeCancellation(execution)
}

export function isToolExecutionRunning(execution: ToolExecutionMessagePart): boolean {
  return !isToolExecutionCancelled(execution)
    && RUNNING_STATUSES.has(String(execution.status || ''))
}

export function isToolExecutionFailed(execution: ToolExecutionMessagePart): boolean {
  if (isToolExecutionCancelled(execution)) return false
  return Boolean(execution.error) || execution.status === 'failed'
}

export function formatToolTraceDuration(durationMs: number): string {
  if (durationMs < 1000) return `${Math.round(durationMs)} ms`
  if (durationMs < 60_000) return `${(durationMs / 1000).toFixed(durationMs < 10_000 ? 1 : 0)} s`
  const totalSeconds = Math.round(durationMs / 1000)
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return seconds ? `${minutes}m ${seconds}s` : `${minutes}m`
}

function traceDurationMs(
  earliestStart: number,
  latestCompletion: number,
  stillRunning: boolean,
): number | null {
  if (!Number.isFinite(earliestStart)) return null
  const end = stillRunning ? Date.now() : latestCompletion
  if (!Number.isFinite(end) || end < earliestStart) return null
  return end - earliestStart
}

function changedFilePaths(execution: ToolExecutionMessagePart): string[] {
  const paths = new Set<string>()
  const record = unwrapRecord(execution.output)
  if (record) {
    const affected = record.affected_files
    if (Array.isArray(affected)) {
      affected.forEach((file) => {
        if (!file || typeof file !== 'object' || Array.isArray(file)) return
        const path = String((file as Record<string, unknown>).path || '').trim()
        if (path) paths.add(path)
      })
    }
    const reportedPath = String(record.path || '').trim()
    if (reportedPath && record.change_summary && typeof record.change_summary === 'object') {
      paths.add(reportedPath)
    }
  }
  if (paths.size === 0 && WRITE_TOOL_NAMES.has(execution.toolName)) {
    const requestedPath = String(argumentRecord(execution)?.path || '').trim()
    if (requestedPath) paths.add(requestedPath)
  }
  return [...paths]
}

function unwrapRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const record = value as Record<string, unknown>
  const nested = record.output
  return nested && typeof nested === 'object' && !Array.isArray(nested)
    ? nested as Record<string, unknown>
    : record
}

function argumentRecord(execution: ToolExecutionMessagePart): Record<string, unknown> | null {
  const value = execution.arguments
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}
