import { invoke, isTauri } from '@tauri-apps/api/core'

let backendBaseUrl: Promise<string> | null = null
let resolvedBackendBaseUrl: string | null = null
const BACKEND_READINESS_TIMEOUT_MS = 60_000
const BACKEND_READINESS_POLL_INTERVAL_MS = 200

export function backendUrl(path: string): Promise<string> {
  if (!isTauri()) return Promise.resolve(path)

  backendBaseUrl ??= invoke<string>('backend_url').then((value) => {
    const url = new URL(value)
    if (url.protocol !== 'http:' && url.protocol !== 'https:') {
      throw new Error(`Unsupported backend protocol: ${url.protocol}`)
    }
    resolvedBackendBaseUrl = url.toString()
    return resolvedBackendBaseUrl
  })

  return backendBaseUrl.then((baseUrl) => new URL(path, baseUrl).toString())
}

export async function initializeBackendUrl(): Promise<void> {
  await backendUrl('/')
}

export async function waitForBackendReady(): Promise<void> {
  const healthUrl = await backendUrl('/health')
  const deadline = Date.now() + BACKEND_READINESS_TIMEOUT_MS
  let lastFailure = ''

  while (Date.now() < deadline) {
    try {
      const response = await fetch(healthUrl, { cache: 'no-store' })
      if (response.ok) return
      lastFailure = `HTTP ${response.status}`
    } catch (error) {
      lastFailure = error instanceof Error ? error.message : String(error)
    }
    await delay(BACKEND_READINESS_POLL_INTERVAL_MS)
  }

  throw new Error(`Backend initialization timed out${lastFailure ? `: ${lastFailure}` : ''}`)
}

async function delay(milliseconds: number): Promise<void> {
  await new Promise(resolve => window.setTimeout(resolve, milliseconds))
}

export function resolvedBackendUrl(path: string): string {
  if (!isTauri()) return path
  if (!resolvedBackendBaseUrl) {
    throw new Error('Backend URL has not been initialized')
  }
  return new URL(path, resolvedBackendBaseUrl).toString()
}
