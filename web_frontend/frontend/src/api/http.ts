import type { FactoryFrontendCommand, FactoryFrontendEvent } from '@/types/protocol'

interface EventResponse {
  event: FactoryFrontendEvent
}

export interface CommandResponse {
  accepted: boolean
  command: FactoryFrontendCommand
}

export interface BlobResponse {
  blob: Blob
  filename: string | null
}

export async function postCommand(command: FactoryFrontendCommand): Promise<CommandResponse> {
  return requestJson<CommandResponse>('/api/commands', {
    method: 'POST',
    body: JSON.stringify({ command }),
  })
}

export async function requestEvent(url: string, init: RequestInit = {}): Promise<FactoryFrontendEvent> {
  const response = await requestJson<EventResponse>(url, init)
  return response.event
}

export async function requestFormEvent(url: string, formData: FormData, init: RequestInit = {}): Promise<FactoryFrontendEvent> {
  const response = await fetch(url, {
    ...init,
    method: init.method || 'POST',
    body: formData,
  })
  if (!response.ok) {
    const text = await response.text()
    throw new Error(text || `HTTP ${response.status}`)
  }
  const data = (await response.json()) as EventResponse
  return data.event
}

export async function requestBlob(url: string, init: RequestInit = {}): Promise<BlobResponse> {
  const response = await fetch(url, init)
  if (!response.ok) {
    const text = await response.text()
    throw new Error(text || `HTTP ${response.status}`)
  }
  return {
    blob: await response.blob(),
    filename: filenameFromDisposition(response.headers.get('content-disposition')),
  }
}

export async function requestJson<T>(url: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init.headers || {}),
    },
  })
  if (!response.ok) {
    const text = await response.text()
    throw new Error(text || `HTTP ${response.status}`)
  }
  return response.json() as Promise<T>
}

export function withQuery(path: string, params: Record<string, string | number | undefined | null>): string {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      search.set(key, String(value))
    }
  })
  const query = search.toString()
  return query ? `${path}?${query}` : path
}

function filenameFromDisposition(disposition: string | null): string | null {
  if (!disposition) return null
  const utf8Match = disposition.match(/filename\*=UTF-8''([^;]+)/i)
  if (utf8Match?.[1]) return decodeURIComponent(utf8Match[1])
  const asciiMatch = disposition.match(/filename="?([^";]+)"?/i)
  return asciiMatch?.[1] || null
}
