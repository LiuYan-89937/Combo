import { onBeforeUnmount, ref, watch, type Ref } from 'vue'
import type { WorkspaceRequestContext } from '@/api/resourceTypes'
import { workspaceApi } from '@/api/workspace'
import { isRemoteResource, workspaceFileReference } from '@/utils/workspaceResources'

export function useWorkspaceResourceUrls(
  sources: Ref<string[]>,
  context: Ref<WorkspaceRequestContext | null | undefined>,
) {
  const urls = ref<Record<string, string>>({})
  let generation = 0

  async function reload(): Promise<void> {
    const currentGeneration = ++generation
    releaseAll()
    const currentContext = context.value
    if (!currentContext) return

    const next: Record<string, string> = {}
    await Promise.all(Array.from(new Set(sources.value)).map(async (source) => {
      const normalized = String(source || '').trim()
      if (!normalized) return
      if (isRemoteResource(normalized)) {
        next[normalized] = normalized
        return
      }
      const reference = workspaceFileReference(normalized)
      if (!reference) return
      try {
        const response = await workspaceApi.rawBlob(reference.scope, reference.path, currentContext)
        if (currentGeneration !== generation) return
        next[normalized] = URL.createObjectURL(response.blob)
      } catch {
        // The resource stays unavailable; the surrounding message remains renderable.
      }
    }))
    if (currentGeneration !== generation) {
      Object.values(next).forEach(releaseObjectUrl)
      return
    }
    urls.value = next
  }

  function resolve(source: string): string | null {
    const normalized = String(source || '').trim()
    if (!normalized) return null
    return isRemoteResource(normalized) ? normalized : urls.value[normalized] || null
  }

  function releaseAll(): void {
    Object.values(urls.value).forEach(releaseObjectUrl)
    urls.value = {}
  }

  watch([sources, context], () => { void reload() }, { immediate: true, deep: true })
  onBeforeUnmount(() => {
    generation += 1
    releaseAll()
  })

  return { resolve }
}

function releaseObjectUrl(url: string): void {
  if (url.startsWith('blob:')) URL.revokeObjectURL(url)
}
