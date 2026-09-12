import { onBeforeUnmount, ref, watch, type Ref } from 'vue'

type UrlLoader = (key: string) => Promise<string | null>

/** How long a failed key waits before it is fetched again. */
const RETRY_AFTER_MS = 3_000

/**
 * Keeps object URLs for a key set that can be rebuilt at any time.
 *
 * Streaming rebuilds a message's parts on every chunk, so the key array handed
 * in is usually a fresh array holding exactly the same keys. Reconciling by
 * content (never by array identity) means a retained key keeps the very same
 * URL string: its <img> is neither unmounted nor re-fetched, so nothing flashes
 * mid-stream. Only keys that really left the set are revoked.
 *
 * `scope` invalidates every cached URL when it changes — for example when a
 * request context switches to another workspace, where the same path resolves
 * to a different file.
 */
export function useReconciledObjectUrls(
  keys: Ref<string[]>,
  load: UrlLoader,
  scope?: Ref<string | null | undefined>,
) {
  const urls = ref<Record<string, string>>({})
  const inFlight = new Set<string>()
  const failed = new Map<string, number>()
  let syncedKeys = ''
  let syncedScope: string | null = null
  let generation = 0

  function releaseAll(): void {
    generation += 1
    Object.values(urls.value).forEach(releaseObjectUrl)
    urls.value = {}
    inFlight.clear()
    failed.clear()
    syncedKeys = ''
  }

  function release(key: string): void {
    releaseObjectUrl(urls.value[key])
    failed.delete(key)
    const next = { ...urls.value }
    delete next[key]
    urls.value = next
  }

  function hasDueRetry(wantedKeys: Set<string>, now: number): boolean {
    for (const [key, retryAt] of failed) {
      if (retryAt <= now && wantedKeys.has(key)) return true
    }
    return false
  }

  async function sync(): Promise<void> {
    const scopeValue = scope ? String(scope.value ?? '') : ''
    if (scopeValue !== syncedScope) {
      releaseAll()
      syncedScope = scopeValue
    }

    const wanted = Array.from(
      new Set(keys.value.map(key => String(key || '').trim()).filter(Boolean)),
    )
    const wantedKeys = new Set(wanted)
    const now = Date.now()
    // An unchanged key set is a no-op: this is the streaming case where the
    // array identity changed but its contents did not. Only a key whose retry
    // window elapsed is allowed to break that no-op.
    if (wanted.join('\u0001') === syncedKeys && !hasDueRetry(wantedKeys, now)) return
    syncedKeys = wanted.join('\u0001')

    for (const key of Object.keys(urls.value)) {
      if (!wantedKeys.has(key)) release(key)
    }
    for (const key of Array.from(failed.keys())) {
      if (!wantedKeys.has(key)) failed.delete(key)
    }

    const currentGeneration = generation
    const missing = wanted.filter(key => (
      !urls.value[key]
      && !inFlight.has(key)
      && (failed.get(key) ?? 0) <= now
    ))
    await Promise.all(missing.map(async (key) => {
      inFlight.add(key)
      try {
        const url = await load(key)
        if (!url) {
          failed.set(key, Date.now() + RETRY_AFTER_MS)
          return
        }
        failed.delete(key)
        if (currentGeneration !== generation) return
        urls.value = { ...urls.value, [key]: url }
      } catch {
        failed.set(key, Date.now() + RETRY_AFTER_MS)
      } finally {
        inFlight.delete(key)
      }
    }))
  }

  watch([keys, ...(scope ? [scope] : [])], () => { void sync() }, { immediate: true, deep: true })
  onBeforeUnmount(() => {
    releaseAll()
  })

  return { urls, reload: sync }
}

function releaseObjectUrl(url: string | undefined): void {
  if (url && url.startsWith('blob:')) URL.revokeObjectURL(url)
}
