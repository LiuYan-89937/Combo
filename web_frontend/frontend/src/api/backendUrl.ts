const BACKEND_READINESS_TIMEOUT_MS = 60_000
const BACKEND_READINESS_POLL_INTERVAL_MS = 200

export function backendUrl(path: string): Promise<string> {
  return Promise.resolve(path)
}

export async function initializeBackendUrl(): Promise<void> {
  return Promise.resolve()
}

export async function restartBackend(): Promise<void> {
  return Promise.resolve()
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
  return path
}
