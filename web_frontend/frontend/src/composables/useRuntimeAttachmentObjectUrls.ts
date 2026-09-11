import { onBeforeUnmount, ref, watch, type Ref } from 'vue'
import { readRuntimeAttachment } from '@/api/attachments'

/**
 * Resolves several runtime attachments at once.
 *
 * A transcript can hold many uploaded images in one turn, so the ids are read
 * as a batch instead of one composable instance per attachment. Object URLs are
 * revoked whenever the id set changes or the component unmounts.
 */
export function useRuntimeAttachmentObjectUrls(ids: Ref<string[]>) {
  const urls = ref<Record<string, string>>({})
  let generation = 0

  function releaseAll(): void {
    Object.values(urls.value).forEach(releaseObjectUrl)
    urls.value = {}
  }

  async function reload(): Promise<void> {
    const currentGeneration = ++generation
    releaseAll()
    const requested = Array.from(new Set(ids.value.map(id => String(id || '').trim()).filter(Boolean)))
    if (requested.length === 0) return

    const next: Record<string, string> = {}
    await Promise.all(requested.map(async (id) => {
      try {
        const blob = await readRuntimeAttachment(id)
        if (currentGeneration !== generation) return
        next[id] = URL.createObjectURL(blob)
      } catch {
        // The image stays unresolved and renders its unavailable placeholder.
      }
    }))
    if (currentGeneration !== generation) {
      Object.values(next).forEach(releaseObjectUrl)
      return
    }
    urls.value = next
  }

  watch(ids, () => { void reload() }, { immediate: true, deep: true })
  onBeforeUnmount(() => {
    generation += 1
    releaseAll()
  })

  return { urls }
}

function releaseObjectUrl(url: string): void {
  if (url.startsWith('blob:')) URL.revokeObjectURL(url)
}
