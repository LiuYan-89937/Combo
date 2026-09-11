/**
 * Copies a rendered image (object URL or resource URL) to the clipboard.
 *
 * Message images are streamed into `blob:` URLs, so the blob is read back
 * through fetch and re-encoded through a canvas when the source cannot be read
 * directly (for example an opaque cross-origin response).
 */
export async function writeClipboardImage(url: string): Promise<void> {
  const normalized = String(url || '').trim()
  if (!normalized) throw new Error('Image is unavailable')
  const blob = await imageBlob(normalized)
  if (!blob) throw new Error('Image is unavailable')
  const clipboardItem = (globalThis as { ClipboardItem?: unknown }).ClipboardItem
  if (!navigator.clipboard?.write || typeof clipboardItem !== 'function') {
    throw new Error('Clipboard image write is unsupported')
  }
  const type = blob.type.startsWith('image/') ? blob.type : 'image/png'
  await navigator.clipboard.write([
    new (clipboardItem as new (items: Record<string, Blob>) => ClipboardItem)({ [type]: blob }),
  ])
}

async function imageBlob(url: string): Promise<Blob | null> {
  try {
    const response = await fetch(url)
    if (response.ok) {
      const blob = await response.blob()
      if (blob.size > 0) return blob
    }
  } catch {
    // Fall through to the decoded image so remote/opaque sources still work.
  }
  return canvasImageBlob(url)
}

function canvasImageBlob(url: string): Promise<Blob | null> {
  return new Promise((resolve) => {
    if (typeof document === 'undefined') {
      resolve(null)
      return
    }
    const image = new Image()
    image.crossOrigin = 'anonymous'
    image.onload = () => {
      try {
        const canvas = document.createElement('canvas')
        canvas.width = image.naturalWidth
        canvas.height = image.naturalHeight
        const context = canvas.getContext('2d')
        if (!context || !canvas.width || !canvas.height) {
          resolve(null)
          return
        }
        context.drawImage(image, 0, 0)
        canvas.toBlob(result => resolve(result), 'image/png')
      } catch {
        resolve(null)
      }
    }
    image.onerror = () => resolve(null)
    image.src = url
  })
}

export async function writeClipboardText(text: string): Promise<void> {
  if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text)
    return
  }
  if (typeof document === 'undefined') {
    throw new Error('Clipboard is unavailable')
  }
  const input = document.createElement('textarea')
  input.value = text
  input.readOnly = true
  input.style.position = 'fixed'
  input.style.inset = '-9999px auto auto -9999px'
  document.body.appendChild(input)
  input.select()
  try {
    if (!document.execCommand('copy')) {
      throw new Error('Clipboard copy command was rejected')
    }
  } finally {
    input.remove()
  }
}
