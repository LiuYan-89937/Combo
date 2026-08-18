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
