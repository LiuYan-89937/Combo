import { request } from './client'
import type { AgentPackageDetail, AgentRelease, PackageListResponse } from './types'

export interface ListPackagesParams {
  q?: string
  limit?: number
  offset?: number
  signal?: AbortSignal
}

/** Search published packages (latest version per package). */
export function listPackages(params: ListPackagesParams = {}): Promise<PackageListResponse> {
  const { q, limit, offset, signal } = params
  return request<PackageListResponse>('/packages', {
    query: { q, limit, offset },
    signal,
  })
}

/** Package detail with every published version, newest first. */
export function fetchPackageDetail(
  publisher: string,
  packageId: string,
  signal?: AbortSignal,
): Promise<AgentPackageDetail> {
  return request<AgentPackageDetail>(
    `/packages/${encodeURIComponent(publisher)}/${encodeURIComponent(packageId)}`,
    { signal },
  )
}

/** Single public release detail. */
export function fetchRelease(releaseId: string, signal?: AbortSignal): Promise<AgentRelease> {
  return request<AgentRelease>(`/releases/${encodeURIComponent(releaseId)}`, { signal })
}

/**
 * Download URL for a release. The backend answers with a 307 to a time-limited
 * OSS signed URL, so we hand the browser a plain navigation link rather than
 * reading the ZIP into memory.
 */
export function releaseDownloadUrl(releaseId: string): string {
  return `/api/v1/releases/${encodeURIComponent(releaseId)}/download`
}
