import { onBeforeUnmount, ref, watch, type Ref } from 'vue'
import { readRuntimeAttachment } from '@/api/attachments'

export function useRuntimeAttachmentObjectUrl(attachmentId: Ref<string | null | undefined>) {
  const url = ref('')
  let generation = 0

  function release(): void {
    if (url.value.startsWith('blob:')) URL.revokeObjectURL(url.value)
    url.value = ''
  }

  async function reload(): Promise<void> {
    const currentGeneration = ++generation
    release()
    const id = String(attachmentId.value || '').trim()
    if (!id) return
    try {
      const blob = await readRuntimeAttachment(id)
      if (currentGeneration !== generation) return
      url.value = URL.createObjectURL(blob)
    } catch {
      // Keep the attachment renderable through its file fallback.
    }
  }

  watch(attachmentId, () => { void reload() }, { immediate: true })
  onBeforeUnmount(() => {
    generation += 1
    release()
  })

  return { url }
}
