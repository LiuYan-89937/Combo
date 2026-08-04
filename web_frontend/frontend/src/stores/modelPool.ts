import { defineStore } from 'pinia'
import { ref } from 'vue'
import { modelPoolApi, type ModelPoolProfile } from '@/api/modelPool'

export const useModelPoolStore = defineStore('modelPool', () => {
  const profiles = ref<ModelPoolProfile[]>([])
  const loaded = ref(false)
  const loading = ref(false)
  const error = ref('')
  let refreshPromise: Promise<void> | null = null

  function profile(profileId: string | null | undefined): ModelPoolProfile | null {
    if (!profileId) return null
    return profiles.value.find(item => item.profile_id === profileId) || null
  }

  async function refresh(): Promise<void> {
    if (refreshPromise) return refreshPromise
    loading.value = true
    refreshPromise = modelPoolApi.profiles()
      .then(response => {
        profiles.value = response.profiles
        loaded.value = true
        error.value = ''
      })
      .catch((reason: unknown) => {
        error.value = reason instanceof Error ? reason.message : String(reason)
        throw reason
      })
      .finally(() => {
        loading.value = false
        refreshPromise = null
      })
    return refreshPromise
  }

  async function ensureLoaded(): Promise<void> {
    if (!loaded.value) await refresh()
  }

  return {
    profiles,
    loaded,
    loading,
    error,
    profile,
    refresh,
    ensureLoaded,
  }
})
