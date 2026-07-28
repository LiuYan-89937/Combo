import { request } from './client'
import type { HubUser } from './types'

/** Absolute path to start GitHub browser OAuth (server sets HttpOnly cookie). */
export const GITHUB_LOGIN_PATH = '/api/v1/auth/github/login'

/** Fetch the current session user, or null when unauthenticated. */
export async function fetchCurrentUser(signal?: AbortSignal): Promise<HubUser | null> {
  try {
    return await request<HubUser>('/auth/me', { signal })
  } catch (error) {
    // A 401 simply means no active session; treat as logged-out, not an error.
    if (error && typeof error === 'object' && 'status' in error && (error as { status: number }).status === 401) {
      return null
    }
    throw error
  }
}

export async function logout(): Promise<void> {
  await request('/auth/logout', { method: 'POST' })
}
