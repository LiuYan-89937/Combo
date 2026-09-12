import { type Ref } from 'vue'
import { readRuntimeAttachment } from '@/api/attachments'
import { useReconciledObjectUrls } from '@/composables/useReconciledObjectUrls'

/**
 * Resolves several runtime attachments at once.
 *
 * A transcript can hold many uploaded images in one turn, so the ids are read
 * as a batch instead of one composable instance per attachment. Streaming
 * rebuilds the surrounding message parts on every chunk, so the ids arrive as a
 * new array each time; the reconciling cache keeps one URL per attachment id and
 * only revokes ids that really left the turn, which is what stops the images
 * from flashing mid-stream.
 */
export function useRuntimeAttachmentObjectUrls(ids: Ref<string[]>) {
  return useReconciledObjectUrls(ids, async (id) => {
    const blob = await readRuntimeAttachment(id)
    return URL.createObjectURL(blob)
  })
}
