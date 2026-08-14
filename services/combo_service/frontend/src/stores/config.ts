/*
 * Public config store. Wraps loadPublicConfig() so the app fetches runtime
 * config (upload limit, repo URL, download targets) once and shares it.
 */
import { ref } from 'vue'
import { defineStore } from 'pinia'
import { FALLBACK_CONFIG, loadPublicConfig, type PublicConfig } from '@/api/config'

export const useConfigStore = defineStore('config', () => {
  const config = ref<PublicConfig>(FALLBACK_CONFIG)
  const loaded = ref(false)
  let inflight: Promise<void> | null = null

  function ensure(): Promise<void> {
    if (loaded.value) return Promise.resolve()
    if (inflight) return inflight
    inflight = loadPublicConfig()
      .then((result) => {
        config.value = result
      })
      .catch(() => {
        config.value = FALLBACK_CONFIG
      })
      .finally(() => {
        loaded.value = true
        inflight = null
      })
    return inflight
  }

  return { config, loaded, ensure }
})
