/*
 * Auth store. Session lives in an HttpOnly cookie set by the server during
 * GitHub OAuth — we never read or store a token here. This store only caches
 * the current-user view and exposes login/logout affordances.
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { fetchCurrentUser, GITHUB_LOGIN_PATH, logout as logoutRequest } from '@/api/auth'
import type { HubUser } from '@/api/types'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<HubUser | null>(null)
  const resolved = ref(false)
  const loading = ref(false)
  let inflight: Promise<HubUser | null> | null = null

  const isAuthenticated = computed(() => user.value !== null)
  const isAdmin = computed(() => user.value?.is_admin === true)

  /** Resolve the session once; subsequent calls reuse the cached result. */
  async function ensure(): Promise<HubUser | null> {
    if (resolved.value) return user.value
    if (inflight) return inflight
    loading.value = true
    inflight = fetchCurrentUser()
      .then((result) => {
        user.value = result
        return result
      })
      .catch(() => {
        // Network/other error: treat as unresolved-but-logged-out for the UI,
        // but do not cache so a later action can retry.
        user.value = null
        return null
      })
      .finally(() => {
        resolved.value = true
        loading.value = false
        inflight = null
      })
    return inflight
  }

  /** Force a fresh session check (used after returning from OAuth). */
  async function refresh(): Promise<HubUser | null> {
    resolved.value = false
    inflight = null
    return ensure()
  }

  /**
   * Begin GitHub OAuth. The server needs an absolute return path; we pass the
   * current location so the user lands back where they started.
   */
  function login(returnTo?: string): void {
    const target = returnTo ?? window.location.pathname + window.location.search
    const url = `${GITHUB_LOGIN_PATH}?return_to=${encodeURIComponent(target)}`
    window.location.assign(url)
  }

  async function logout(): Promise<void> {
    try {
      await logoutRequest()
    } finally {
      user.value = null
      resolved.value = true
    }
  }

  return { user, resolved, loading, isAuthenticated, isAdmin, ensure, refresh, login, logout }
})
