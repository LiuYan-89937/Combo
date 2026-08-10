import { backendUrl } from './backendUrl'
import type { RuntimeAttachmentInput } from '@/types/protocol'

interface AttachmentUploadResponse {
  attachment: RuntimeAttachmentInput
}

export async function uploadRuntimeAttachment(file: File): Promise<RuntimeAttachmentInput> {
  const formData = new FormData()
  formData.append('file', file, file.name)
  const response = await fetch(await backendUrl('/api/attachments'), {
    method: 'POST',
    body: formData,
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    throw new Error(String(payload?.detail || `Attachment upload failed with HTTP ${response.status}`))
  }
  const payload = await response.json() as AttachmentUploadResponse
  return payload.attachment
}
