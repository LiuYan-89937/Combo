import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  modelPoolApi,
  type LocalModelDefaultRole,
  type LocalModelDefaults,
  type LocalModelProfile,
} from '@/api/modelPool'

const EMPTY_DEFAULTS: LocalModelDefaults = {
  main: null,
  task: null,
  compression: null,
  embedding: null,
  image_generation: null,
}

export const useModelPoolStore = defineStore('modelPool', () => {
  const profiles = ref<LocalModelProfile[]>([])
  const defaults = ref<LocalModelDefaults>({ ...EMPTY_DEFAULTS })
  const loaded = ref(false)
  const loading = ref(false)
  const error = ref('')
  let refreshPromise: Promise<void> | null = null

  const profilesById = computed(() => new Map(
    profiles.value.map((profile) => [profile.profile_id, profile]),
  ))

  function setConfiguration(
    nextProfiles: LocalModelProfile[],
    nextDefaults: LocalModelDefaults,
  ): void {
    profiles.value = [...nextProfiles]
    defaults.value = { ...EMPTY_DEFAULTS, ...nextDefaults }
    loaded.value = true
    error.value = ''
  }

  function upsertProfile(profile: LocalModelProfile): void {
    const index = profiles.value.findIndex((item) => item.profile_id === profile.profile_id)
    if (index < 0) {
      profiles.value = [...profiles.value, profile]
      return
    }
    const next = [...profiles.value]
    next[index] = profile
    profiles.value = next
  }

  function removeProfile(profileId: string): void {
    profiles.value = profiles.value.filter((profile) => profile.profile_id !== profileId)
    const nextDefaults = { ...defaults.value }
    for (const role of Object.keys(nextDefaults) as LocalModelDefaultRole[]) {
      if (nextDefaults[role] === profileId) nextDefaults[role] = null
    }
    defaults.value = nextDefaults
  }

  function setDefault(role: LocalModelDefaultRole, profileId: string | null): void {
    defaults.value = { ...defaults.value, [role]: profileId }
  }

  function profile(profileId: string | null | undefined): LocalModelProfile | null {
    if (!profileId) return null
    return profilesById.value.get(profileId) || null
  }

  function defaultProfile(role: LocalModelDefaultRole): LocalModelProfile | null {
    return profile(defaults.value[role])
  }

  async function refresh(): Promise<void> {
    if (refreshPromise) return refreshPromise
    loading.value = true
    const pending = Promise.all([modelPoolApi.profiles(), modelPoolApi.defaults()])
      .then(([profileData, defaultData]) => {
        setConfiguration(profileData.profiles, defaultData.defaults)
      })
      .catch((reason: unknown) => {
        error.value = reason instanceof Error ? reason.message : String(reason)
        throw reason
      })
      .finally(() => {
        loading.value = false
        refreshPromise = null
      })
    refreshPromise = pending
    return pending
  }

  async function ensureLoaded(): Promise<void> {
    if (loaded.value) return
    await refresh()
  }

  return {
    profiles,
    defaults,
    loaded,
    loading,
    error,
    setConfiguration,
    upsertProfile,
    removeProfile,
    setDefault,
    profile,
    defaultProfile,
    refresh,
    ensureLoaded,
  }
})
