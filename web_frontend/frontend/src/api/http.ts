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

export function requestFormEvent(
  url: string,
  formData: FormData,
  onUploadProgress?: (percent: number) => void,
): Promise<FactoryFrontendEvent> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest()
    request.open('POST', url)
    request.upload.addEventListener('progress', (event) => {
      if (!event.lengthComputable || event.total <= 0) return
      onUploadProgress?.(Math.round((event.loaded / event.total) * 100))
    })
    request.addEventListener('load', () => {
      if (request.status < 200 || request.status >= 300) {
        reject(new Error(request.responseText || `HTTP ${request.status}`))
        return
      }
      try {
        const data = JSON.parse(request.responseText) as EventResponse
        resolve(data.event)
      } catch (error) {
        reject(error)
      }
    })
    request.addEventListener('error', () => reject(new Error('Knowledge upload request failed')))
    request.addEventListener('abort', () => reject(new Error('Knowledge upload request was cancelled')))
    request.send(formData)
  })
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
