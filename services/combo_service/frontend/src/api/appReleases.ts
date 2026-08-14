import { request } from './client'
import { putToObjectStore, type DirectUploadProgress } from './uploads'
import type {
  AppRelease,
  AppReleaseAsset,
  CreateAppAssetResponse,
} from './types'

export function listAppReleases(limit = 20, signal?: AbortSignal): Promise<AppRelease[]> {
  return request<AppRelease[]>('/app-releases', { query: { limit }, signal })
}

export function latestAppRelease(signal?: AbortSignal): Promise<AppRelease> {
  return request<AppRelease>('/app-releases/latest', { signal })
}

export function listAdminAppReleases(
  limit = 50,
  signal?: AbortSignal,
): Promise<AppRelease[]> {
  return request<AppRelease[]>('/admin/app-releases', {
    query: { limit },
    signal,
  })
}

export function fetchAdminAppRelease(
  releaseId: string,
  signal?: AbortSignal,
): Promise<AppRelease> {
  return request<AppRelease>(
    `/admin/app-releases/${encodeURIComponent(releaseId)}`,
    { signal },
  )
}

export function createAppRelease(input: {
  version: string
  title: string
  notes_markdown: string
}): Promise<AppRelease> {
  return request<AppRelease>('/admin/app-releases', {
    method: 'POST',
    body: input,
  })
}

export function updateAppRelease(
  releaseId: string,
  input: { title: string; notes_markdown: string },
): Promise<AppRelease> {
  return request<AppRelease>(
    `/admin/app-releases/${encodeURIComponent(releaseId)}`,
    { method: 'PUT', body: input },
  )
}

export function deleteAppRelease(releaseId: string): Promise<void> {
  return request<void>(
    `/admin/app-releases/${encodeURIComponent(releaseId)}`,
    { method: 'DELETE' },
  )
}

export async function uploadAppReleaseAsset(
  releaseId: string,
  input: {
    assetKind: 'installer' | 'updater'
    platform: 'macos' | 'windows'
    architecture: string
    file: File
    updaterSignature?: string
  },
  handlers: {
    onProgress?: (progress: DirectUploadProgress) => void
    signal?: AbortSignal
  } = {},
): Promise<AppReleaseAsset> {
  const created = await request<CreateAppAssetResponse>(
    `/admin/app-releases/${encodeURIComponent(releaseId)}/assets`,
    {
      method: 'POST',
      body: {
        asset_kind: input.assetKind,
        platform: input.platform,
        architecture: input.architecture,
        filename: input.file.name,
        size_bytes: input.file.size,
        updater_signature: input.updaterSignature || '',
      },
      signal: handlers.signal,
    },
  )
  await putToObjectStore(created.upload_request, input.file, handlers)
  return request<AppReleaseAsset>(
    `/admin/app-releases/${encodeURIComponent(releaseId)}/assets/` +
      `${encodeURIComponent(created.asset.asset_id)}/complete`,
    { method: 'POST', signal: handlers.signal },
  )
}

export function deleteAppReleaseAsset(
  releaseId: string,
  assetId: string,
): Promise<void> {
  return request<void>(
    `/admin/app-releases/${encodeURIComponent(releaseId)}/assets/` +
      `${encodeURIComponent(assetId)}`,
    { method: 'DELETE' },
  )
}

export function publishAppRelease(releaseId: string): Promise<AppRelease> {
  return request<AppRelease>(
    `/admin/app-releases/${encodeURIComponent(releaseId)}/publish`,
    { method: 'POST' },
  )
}
