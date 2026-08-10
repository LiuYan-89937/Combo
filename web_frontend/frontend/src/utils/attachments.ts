import type { RuntimeAttachmentInput } from '@/types/protocol'
import { uploadRuntimeAttachment } from '@/api/attachments'

export const MAX_RUNTIME_ATTACHMENTS = 9

export async function runtimeFileAttachmentFromFile(
  file: File,
  options: { name?: string } = {}
): Promise<RuntimeAttachmentInput> {
  const uploadFile = options.name && options.name !== file.name
    ? new File([file], options.name, { type: file.type, lastModified: file.lastModified })
    : file
  return uploadRuntimeAttachment(uploadFile)
}

export function pastedImageFiles(event: ClipboardEvent, fallbackName: (file: File, index: number) => string): File[] {
  const items = Array.from(event.clipboardData?.items || [])
  const files: File[] = []
  for (const item of items) {
    if (item.kind !== 'file' || !item.type.startsWith('image/')) continue
    const file = item.getAsFile()
    if (!file) continue
    files.push(
      file.name
        ? file
        : new File([file], fallbackName(file, files.length), { type: file.type, lastModified: file.lastModified })
    )
  }
  return files
}

export function extensionFromMimeType(mimeType: string): string {
  const subtype = mimeType.split('/')[1]?.split(';')[0]?.trim().toLowerCase()
  if (!subtype) return 'png'
  if (subtype === 'jpeg') return 'jpg'
  if (!subtype.includes('+')) return subtype
  return subtype.slice(0, subtype.indexOf('+')) || 'png'
}
