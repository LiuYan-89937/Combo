import { computed, type Ref } from 'vue'
import type { WorkspaceRequestContext } from '@/api/resourceTypes'
import { workspaceApi } from '@/api/workspace'
import { useReconciledObjectUrls } from '@/composables/useReconciledObjectUrls'
import { isRemoteResource, workspaceFileReference } from '@/utils/workspaceResources'

/**
 * Resolves workspace file references to browser-usable URLs.
 *
 * Callers recompute their source list freely — during streaming they do it for
 * every chunk — so the cache reconciles by content and keeps the URL of a path
 * that is still listed instead of revoking and re-fetching it, which would make
 * every visible image blink. Switching to another workspace invalidates the
 * whole cache, because the same path then points at a different file.
 */
export function useWorkspaceResourceUrls(
  sources: Ref<string[]>,
  context: Ref<WorkspaceRequestContext | null | undefined>,
) {
  const scope = computed(() => contextSignature(context.value))
  const { urls } = useReconciledObjectUrls(sources, async (source) => {
    if (isRemoteResource(source)) return source
    const reference = workspaceFileReference(source)
    const requestContext = context.value
    if (!reference || !requestContext) return null
    const response = await workspaceApi.rawBlob(reference.scope, reference.path, requestContext)
    return URL.createObjectURL(response.blob)
  }, scope)

  function resolve(source: string): string | null {
    const normalized = String(source || '').trim()
    if (!normalized) return null
    return isRemoteResource(normalized) ? normalized : urls.value[normalized] || null
  }

  return { resolve }
}

function contextSignature(context: WorkspaceRequestContext | null | undefined): string {
  if (!context) return ''
  return [
    context.resourceMode,
    context.packageId,
    context.packageSessionId,
    context.workspaceId,
    context.groupId,
  ]
    .map(value => String(value ?? ''))
    .join('\u0000')
}
