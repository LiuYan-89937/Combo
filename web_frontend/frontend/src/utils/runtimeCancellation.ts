const CANCELLATION_CODES = new Set([
  'runtime_cancelled',
  'runtime_steered',
  'user_cancel',
  'user_cancelled',
  'user-cancelled',
])

const CANCELLATION_STATUSES = new Set(['cancelled', 'steered', 'superseded'])

export function isRuntimeCancellation(value: unknown): boolean {
  const signal = normalized(value)
  if (CANCELLATION_CODES.has(signal) || signal === 'model generation was superseded.') return true
  return cancellationRecords(value).some(isCancellationRecord)
}

function cancellationRecords(value: unknown): Record<string, unknown>[] {
  const root = recordValue(value)
  if (!root) return []
  const records: Record<string, unknown>[] = []
  const pending = [root]
  const visited = new Set<Record<string, unknown>>()
  while (pending.length > 0) {
    const record = pending.shift()
    if (!record || visited.has(record)) continue
    visited.add(record)
    records.push(record)
    for (const key of ['error', 'result', 'output', 'observation', 'details']) {
      const nested = recordValue(record[key])
      if (nested) pending.push(nested)
    }
  }
  return records
}

function isCancellationRecord(value: Record<string, unknown>): boolean {
  const code = normalized(value.code || value.error_code)
  const signal = normalized(value.error || value.cancel_reason || value.stop_reason)
  const category = normalized(value.category)
  const terminalStatus = normalized(value.terminal_status)
  const statuses = [value.status, value.execution_status].map(normalized)
  const exceptionType = normalized(value.exception_type)
  const message = normalized(value.message || value.reason)
  return CANCELLATION_CODES.has(code)
    || CANCELLATION_CODES.has(signal)
    || category === 'cancelled'
    || terminalStatus === 'cancelled'
    || statuses.some(status => CANCELLATION_STATUSES.has(status))
    || exceptionType === 'runtimemodelgenerationinterrupted'
    || message === 'model generation was superseded.'
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}

function normalized(value: unknown): string {
  return typeof value === 'string' ? value.trim().toLowerCase() : ''
}
