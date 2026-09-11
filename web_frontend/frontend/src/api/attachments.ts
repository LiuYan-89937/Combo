import { backendUrl } from './backendUrl'
import { runtimeClientInstanceId, runtimePrincipalId } from './runtimeIdentity'
import type { RuntimeAttachmentInput } from '@/types/protocol'
import { runtimeLocale } from '@/i18n'

interface AttachmentUploadResponse {
  attachment: RuntimeAttachmentInput
}

export interface AttachmentNativePath {
  native_path: string
  name: string
  mime_type: string | null
}

function runtimeHeaders(): Record<string, string> {
  return {
    'X-Combo-Principal': runtimePrincipalId(),
    'X-Combo-Client': runtimeClientInstanceId(),
    'X-Combo-Timezone': Intl.DateTimeFormat().resolvedOptions().timeZone,
    'X-Combo-Locale': runtimeLocale(),
  }
}

export async function uploadRuntimeAttachment(file: File): Promise<RuntimeAttachmentInput> {
  const formData = new FormData()
  formData.append('file', file, file.name)
  const response = await fetch(await backendUrl('/api/attachments'), {
    method: 'POST',
    headers: {
      'X-Combo-Principal': runtimePrincipalId(),
      'X-Combo-Client': runtimeClientInstanceId(),
      'X-Combo-Timezone': Intl.DateTimeFormat().resolvedOptions().timeZone,
      'X-Combo-Locale': runtimeLocale(),
    },
    body: formData,
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    throw new Error(String(payload?.detail || `Attachment upload failed with HTTP ${response.status}`))
  }
  const payload = await response.json() as AttachmentUploadResponse
  return payload.attachment
}

export async function readRuntimeAttachment(attachmentId: string): Promise<Blob> {
  const response = await fetch(await backendUrl(`/api/attachments/${encodeURIComponent(attachmentId)}`), {
    headers: runtimeHeaders(),
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    throw new Error(String(payload?.detail || `Attachment read failed with HTTP ${response.status}`))
  }
  return response.blob()
}

/**
 * Local filesystem path of a staged upload.
 *
 * Uploads live in the attachment staging store rather than the workspace, so the
 * workspace native-path endpoint cannot resolve them; the system viewer needs a
 * real path.
 */
export async function runtimeAttachmentNativePath(
  attachmentId: string,
): Promise<AttachmentNativePath> {
  const response = await fetch(
    await backendUrl(`/api/attachments/${encodeURIComponent(attachmentId)}/native-path`),
    { headers: runtimeHeaders() },
  )
  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    throw new Error(String(payload?.detail || `Attachment path lookup failed with HTTP ${response.status}`))
  }
  return await response.json() as AttachmentNativePath
}
