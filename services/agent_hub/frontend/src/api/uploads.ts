import { request } from './client'
import type { CreateUploadResponse, HubUpload, UploadRequest } from './types'

/** Step 1: register an upload and receive a signed OSS PUT request. */
export function createUpload(filename: string, sizeBytes: number): Promise<CreateUploadResponse> {
  return request<CreateUploadResponse>('/uploads', {
    method: 'POST',
    body: { filename, size_bytes: sizeBytes },
  })
}

/** Step 4: mark the OSS object uploaded so validation can be queued. */
export function completeUpload(uploadId: string): Promise<HubUpload> {
  return request<HubUpload>(`/uploads/${encodeURIComponent(uploadId)}/complete`, {
    method: 'POST',
  })
}

/** Poll a single upload's current status. */
export function fetchUpload(uploadId: string, signal?: AbortSignal): Promise<HubUpload> {
  return request<HubUpload>(`/uploads/${encodeURIComponent(uploadId)}`, { signal })
}

/** List the current user's submissions. */
export function listUploads(limit = 50, signal?: AbortSignal): Promise<HubUpload[]> {
  return request<HubUpload[]>('/uploads', { query: { limit }, signal })
}

export interface DirectUploadProgress {
  loaded: number
  total: number
}

/**
 * Step 3: PUT the raw file directly to OSS using the signed request exactly as
 * returned — headers must not be altered or the signature breaks. Uses
 * XMLHttpRequest for real progress and cancellation. This does not carry
 * credentials (it is a signed URL, cross-origin to OSS).
 */
export function putToObjectStore(
  uploadRequest: UploadRequest,
  file: File,
  handlers: {
    onProgress?: (progress: DirectUploadProgress) => void
    signal?: AbortSignal
  } = {},
): Promise<void> {
  const { onProgress, signal } = handlers
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open(uploadRequest.method, uploadRequest.url, true)

    for (const [key, value] of Object.entries(uploadRequest.headers)) {
      xhr.setRequestHeader(key, value)
    }

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) {
        onProgress({ loaded: event.loaded, total: event.total })
      }
    }

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve()
      else reject(new Error(`object storage rejected the upload (${xhr.status})`))
    }
    xhr.onerror = () => reject(new Error('object storage upload failed'))
    xhr.ontimeout = () => reject(new Error('object storage upload timed out'))
    xhr.onabort = () => reject(new DOMException('aborted', 'AbortError'))

    if (signal) {
      if (signal.aborted) {
        xhr.abort()
        return
      }
      signal.addEventListener('abort', () => xhr.abort(), { once: true })
    }

    xhr.send(file)
  })
}
