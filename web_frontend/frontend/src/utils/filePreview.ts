import type { WorkspaceFileView } from '@/types/protocol'

export type FilePreviewKind = 'text' | 'markdown' | 'code' | 'image' | 'pdf' | 'unsupported'

const CODE_EXTENSIONS = new Set([
  'bash', 'c', 'cc', 'cpp', 'css', 'go', 'h', 'hpp', 'html', 'java', 'js', 'jsx',
  'json', 'jsonl', 'kt', 'php', 'py', 'rb', 'rs', 'sh', 'sql', 'swift', 'toml',
  'ts', 'tsx', 'vue', 'xml', 'yaml', 'yml', 'zsh',
])
const IMAGE_EXTENSIONS = new Set(['svg', 'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'tif', 'tiff', 'heic'])

export function fileExtension(file: WorkspaceFileView): string {
  return file.name.split('.').pop()?.toLowerCase() || ''
}

export function filePreviewKind(file: WorkspaceFileView): FilePreviewKind {
  const extension = fileExtension(file)
  const mimeType = String(file.mimeType || '').toLowerCase()
  if (file.kind === 'text' && ['md', 'markdown', 'mdx'].includes(extension)) return 'markdown'
  if (file.kind === 'text' && CODE_EXTENSIONS.has(extension)) return 'code'
  if (mimeType.startsWith('image/') || IMAGE_EXTENSIONS.has(extension)) return 'image'
  if (mimeType === 'application/pdf' || extension === 'pdf') return 'pdf'
  if (file.kind === 'text') return 'text'
  return 'unsupported'
}

export function filePreviewDataUrl(file: WorkspaceFileView): string {
  if (file.contentBase64) {
    return `data:${file.mimeType || 'application/octet-stream'};base64,${file.contentBase64}`
  }
  if (fileExtension(file) === 'svg' && file.content) {
    return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(file.content)}`
  }
  return ''
}
