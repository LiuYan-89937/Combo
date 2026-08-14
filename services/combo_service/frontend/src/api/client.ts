import type { ApiErrorBody } from './types'

/**
 * Central HTTP client. All API URLs are built from a single base so business
 * components never concatenate endpoints or hardcode a host.
 */
export const API_BASE = '/api/v1'

const DEFAULT_TIMEOUT_MS = 15_000

/** A parsed, user-presentable API error preserving the machine contract. */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly requestId?: string

  constructor(status: number, body: ApiErrorBody) {
    super(body.message || 'request failed')
    this.name = 'ApiError'
    this.status = status
    this.code = body.code || 'unknown_error'
    this.requestId = body.request_id
  }
}

/** Raised when a request times out or the network is unreachable. */
export class NetworkError extends Error {
  readonly kind: 'timeout' | 'offline'
  constructor(kind: 'timeout' | 'offline', message: string) {
    super(message)
    this.name = 'NetworkError'
    this.kind = kind
  }
}

interface RequestOptions {
  method?: string
  body?: unknown
  query?: Record<string, string | number | undefined>
  signal?: AbortSignal
  timeoutMs?: number
}

function buildUrl(path: string, query?: RequestOptions['query']): string {
  const url = path.startsWith('/api') || path.startsWith('/health') ? path : `${API_BASE}${path}`
  if (!query) return url
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== '') params.set(key, String(value))
  }
  const qs = params.toString()
  return qs ? `${url}?${qs}` : url
}

async function parseError(response: Response): Promise<ApiError> {
  let body: ApiErrorBody = { code: 'unknown_error', message: response.statusText }
  try {
    const data = await response.json()
    if (data && typeof data === 'object' && 'error' in data && data.error) {
      body = data.error as ApiErrorBody
    } else if (data && typeof data === 'object' && 'detail' in data) {
      const detail = data.detail
      body = {
        code: 'validation_error',
        message: Array.isArray(detail)
          ? detail
              .map((item) =>
                item && typeof item === 'object' && 'msg' in item
                  ? String(item.msg)
                  : String(item),
              )
              .join('；')
          : String(detail),
      }
    } else if (data && typeof data === 'object' && 'message' in data) {
      body = data as ApiErrorBody
    }
  } catch {
    // Non-JSON error response; keep the status-line fallback.
  }
  // Preserve a request id surfaced via header when the body omits it.
  const headerId = response.headers.get('X-Request-ID')
  if (headerId && !body.request_id) body.request_id = headerId
  return new ApiError(response.status, body)
}

/**
 * Perform a JSON request against the API. Cookie credentials are always
 * included so session auth works same-origin.
 */
export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, query, signal, timeoutMs = DEFAULT_TIMEOUT_MS } = options

  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(new DOMException('timeout', 'TimeoutError')), timeoutMs)

  // Chain an external abort signal (e.g. search race cancellation).
  if (signal) {
    if (signal.aborted) controller.abort(signal.reason)
    else signal.addEventListener('abort', () => controller.abort(signal.reason), { once: true })
  }

  const headers: Record<string, string> = { Accept: 'application/json' }
  let payload: BodyInit | undefined
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
    payload = JSON.stringify(body)
  }

  try {
    const response = await fetch(buildUrl(path, query), {
      method,
      headers,
      body: payload,
      credentials: 'include',
      signal: controller.signal,
    })

    if (!response.ok) throw await parseError(response)
    if (response.status === 204) return undefined as T
    const text = await response.text()
    return (text ? JSON.parse(text) : undefined) as T
  } catch (error) {
    if (error instanceof ApiError) throw error
    if (error instanceof DOMException && error.name === 'AbortError') {
      // Distinguish a timeout abort from an external cancellation.
      if (controller.signal.reason instanceof DOMException && controller.signal.reason.name === 'TimeoutError') {
        throw new NetworkError('timeout', 'request timed out')
      }
      throw error // external cancellation — let caller ignore it
    }
    throw new NetworkError('offline', 'network request failed')
  } finally {
    clearTimeout(timeout)
  }
}
